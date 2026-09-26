import hashlib
import os
import shutil
import time
from pathlib import Path

import pytest

from keepreadable.application.archive_service import ArchiveService
from keepreadable.application.audit_service import (
    AuditEngine,
    AuditProgress,
    AuditStage,
    AuditStateError,
)
from keepreadable.config.settings import Settings
from keepreadable.domain.enums import AuditMode, AuditStatus, FindingCode, HealthState
from keepreadable.integrations.ffmpeg import FFmpegAdapter
from keepreadable.integrations.siegfried import SiegfriedAdapter
from keepreadable.integrations.tool_locator import ToolLocator, ToolName
from keepreadable.persistence.database import Database
from keepreadable.persistence.repositories import (
    FileRecordRepository,
    FindingRepository,
    ObservationRepository,
)
from keepreadable.policies.registry import PolicyRegistry
from keepreadable.utilities.cancellation import CancellationToken
from keepreadable.validators.registry import ValidatorRegistry
from tests.fixture_factory import (
    make_encrypted_pdf,
    make_jpeg,
    make_png_named_jpg,
    make_unknown_binary,
    make_zip,
    truncate_file,
)


def snapshot_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def build_engine(
    tmp_path: Path,
    *,
    siegfried_enabled: bool = True,
    batch_size: int = 20,
    worker_count: int = 4,
    media_decode_workers: int = 1,
) -> tuple[AuditEngine, ArchiveService, Database]:
    database = Database(tmp_path / "data" / "keepreadable.db")
    database.initialize()
    settings = Settings(
        worker_count=worker_count,
        media_decode_workers=media_decode_workers,
        persistence_batch_size=batch_size,
        identification_batch_size=batch_size,
    )
    locator = ToolLocator()
    sf_path = locator.locate(ToolName.SIEGFRIED)
    sf_home = locator.siegfried_home()
    siegfried = (
        SiegfriedAdapter(sf_path, sf_home, timeout=60, multi=4)
        if siegfried_enabled and sf_path and sf_home
        else None
    )
    ffmpeg_path = locator.locate(ToolName.FFMPEG)
    ffprobe_path = locator.locate(ToolName.FFPROBE)
    ffmpeg = (
        FFmpegAdapter(ffmpeg_path, ffprobe_path, timeout=60)
        if ffmpeg_path and ffprobe_path
        else None
    )
    validators = ValidatorRegistry(ffmpeg=ffmpeg)
    policy = PolicyRegistry.load_default()
    engine = AuditEngine(
        database,
        settings,
        siegfried=siegfried,
        ffmpeg=ffmpeg,
        validators=validators,
        policy=policy,
    )
    return engine, ArchiveService(database, settings, tmp_path / "data"), database


def test_quick_then_deep_real_tools_and_immutability(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    root.mkdir()
    make_jpeg(root / "healthy.jpg")
    make_png_named_jpg(root / "disguised.jpg")
    truncate_file(make_jpeg(root / "truncated.jpg"), 0.65)
    make_zip(root / "archive.zip", {"entry.txt": b"content"})
    make_unknown_binary(root / "unknown")
    make_encrypted_pdf(root / "protected.pdf")
    shutil.copyfile(root / "healthy.jpg", root / "copy.jpg")
    before = snapshot_hashes(root)

    engine, archives, database = build_engine(tmp_path)
    archive = archives.add_archive("Fixture", root)
    assert archive.id is not None
    quick = engine.start(archive.id, AuditMode.QUICK)
    assert quick.status is AuditStatus.COMPLETED
    assert archives.overview(archive.id).coverage_percent == 0
    deep = engine.start(archive.id, AuditMode.DEEP)
    assert deep.status is AuditStatus.COMPLETED
    overview = archives.overview(archive.id)
    assert overview.coverage_percent == 100
    assert snapshot_hashes(root) == before

    with database.session() as session:
        records = FileRecordRepository(session).list_present(archive.id, 0, 100)
        health = {record.relative_path: record.last_health for record in records}
        assert health == {
            "archive.zip": HealthState.HEALTHY,
            "copy.jpg": HealthState.HEALTHY,
            "disguised.jpg": HealthState.REVIEW,
            "healthy.jpg": HealthState.HEALTHY,
            "protected.pdf": HealthState.REVIEW,
            "truncated.jpg": HealthState.UNREADABLE,
            "unknown": HealthState.UNKNOWN,
        }
        assert ObservationRepository(session).count_for_run(quick.id or 0) == len(records)
        assert ObservationRepository(session).count_for_run(deep.id or 0) == len(records)
        findings = FindingRepository(session).latest_findings(archive.id)
        assert any(item.code == FindingCode.EXTENSION_MISMATCH for item in findings)
        assert any(item.code == FindingCode.DUPLICATE_CONTENT for item in findings)
        finding_ids = {item.id for item in findings}

    second_deep = engine.start(archive.id, AuditMode.DEEP)
    assert second_deep.status is AuditStatus.COMPLETED
    with database.session() as session:
        assert ObservationRepository(session).count_for_run(second_deep.id or 0) == 7
        assert {
            item.id for item in FindingRepository(session).latest_findings(archive.id)
        } == finding_ids


def test_longitudinal_changes_missing_and_move(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    root.mkdir()
    initial = {
        "modified.txt": "modify00",
        "silent.txt": "silent00",
        "deleted.txt": "delete00",
        "moved.txt": "move0000",
    }
    for name, content in initial.items():
        (root / name).write_text(content, encoding="utf-8")
    engine, archives, database = build_engine(tmp_path)
    archive = archives.add_archive("Longitudinal", root)
    assert archive.id is not None
    assert engine.start(archive.id, AuditMode.DEEP).status is AuditStatus.COMPLETED

    (root / "modified.txt").write_text("edited!!", encoding="utf-8")
    silent = root / "silent.txt"
    original_stat = silent.stat()
    silent.write_text("changed!", encoding="utf-8")
    os.utime(silent, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    (root / "deleted.txt").unlink()
    (root / "moved.txt").rename(root / "renamed.txt")

    second = engine.start(archive.id, AuditMode.DEEP, force_deep_all=True)
    assert second.status is AuditStatus.COMPLETED
    with database.session() as session:
        findings = FindingRepository(session).list(run_id=second.id)
        integrity = [
            finding for finding in findings if finding.code == FindingCode.INTEGRITY_MISMATCH
        ]
        assert {finding.severity.value for finding in integrity} == {"medium", "high"}
        missing = [finding for finding in findings if finding.code == FindingCode.FILE_MISSING]
        assert {finding.severity.value for finding in missing} == {"medium", "info"}
        records = FileRecordRepository(session).list_present(archive.id, 0, 20)
        renamed = next(record for record in records if record.relative_path == "renamed.txt")
        observation = ObservationRepository(session).latest_for_file(renamed.id or 0)
        assert observation is not None
        assert observation.change_kind.value == "moved"


def test_missing_tools_still_validate_by_extension(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    root.mkdir()
    make_jpeg(root / "image.jpg")
    engine, archives, database = build_engine(tmp_path, siegfried_enabled=False)
    archive = archives.add_archive("No tools", root)
    assert archive.id is not None
    run = engine.start(archive.id, AuditMode.QUICK)
    assert run.status is AuditStatus.COMPLETED
    with database.session() as session:
        record = FileRecordRepository(session).list_present(archive.id, 0, 10)[0]
        observation = ObservationRepository(session).latest_for_file(record.id or 0)
        assert observation is not None
        assert observation.health is HealthState.UNKNOWN
        assert observation.structural_status.value == "passed"
        assert any(
            item.code == FindingCode.TOOL_UNAVAILABLE
            for item in FindingRepository(session).list(run_id=run.id)
        )


def test_pause_during_discovery_resumes_cleanly(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    root.mkdir()
    for index in range(120):
        (root / f"{index:03}.txt").write_text("x", encoding="utf-8")
    engine, archives, database = build_engine(tmp_path, siegfried_enabled=False, batch_size=20)
    archive = archives.add_archive("Discovery pause", root)
    assert archive.id is not None
    token = CancellationToken()

    def pause(progress: AuditProgress) -> None:
        if progress.stage is AuditStage.DISCOVERING and progress.files_discovered >= 40:
            token.cancel("pause")

    paused = engine.start(archive.id, AuditMode.QUICK, cancel=token, on_progress=pause)
    assert paused.status is AuditStatus.PAUSED
    resumed = engine.resume(paused.id or 0)
    assert resumed.status is AuditStatus.COMPLETED
    with database.session() as session:
        assert ObservationRepository(session).count_for_run(resumed.id or 0) == 120


@pytest.mark.slow
def test_pause_and_resume_ten_thousand_files(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    root.mkdir()
    for index in range(10_000):
        (root / f"{index:05}.txt").write_text("x", encoding="utf-8")
    engine, archives, database = build_engine(tmp_path, siegfried_enabled=False, batch_size=500)
    archive = archives.add_archive("Large", root)
    assert archive.id is not None
    token = CancellationToken()
    processing_started = time.monotonic()

    def pause(progress: AuditProgress) -> None:
        if progress.stage is AuditStage.PROCESSING and progress.files_processed >= 4000:
            token.cancel("pause")

    paused = engine.start(archive.id, AuditMode.QUICK, cancel=token, on_progress=pause)
    pause_duration = time.monotonic() - processing_started
    assert paused.status is AuditStatus.PAUSED
    assert 4000 <= paused.files_processed < 10_000
    resumed = build_engine(tmp_path, siegfried_enabled=False, batch_size=500)[0].resume(
        paused.id or 0
    )
    assert resumed.status is AuditStatus.COMPLETED
    with database.session() as session:
        assert ObservationRepository(session).count_for_run(resumed.id or 0) == 10_000
    assert pause_duration < 60


def test_processing_emits_intra_batch_progress_from_engine_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "archive"
    root.mkdir()
    for index in range(20):
        (root / f"{index:03}.txt").write_text("x", encoding="utf-8")
    engine, archives, _database = build_engine(
        tmp_path, siegfried_enabled=False, batch_size=20, worker_count=2
    )
    archive = archives.add_archive("Progress", root)
    assert archive.id is not None
    original = engine._work_one

    def slow_work(*args: object, **kwargs: object) -> object:
        time.sleep(0.08)
        return original(*args, **kwargs)

    monkeypatch.setattr(engine, "_work_one", slow_work)
    processing_events: list[AuditProgress] = []
    run = engine.start(
        archive.id,
        AuditMode.QUICK,
        on_progress=lambda progress: (
            processing_events.append(progress) if progress.stage is AuditStage.PROCESSING else None
        ),
    )
    assert run.status is AuditStatus.COMPLETED
    assert any(0 < event.files_processed < 20 for event in processing_events)
    assert all(event.files_total_estimate == 20 for event in processing_events)


def test_disconnect_interrupts_without_marking_missing_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "archive"
    disconnected = tmp_path / "archive-disconnected"
    root.mkdir()
    for index in range(300):
        (root / f"{index:03}.txt").write_text("x", encoding="utf-8")
    engine, archives, database = build_engine(tmp_path, siegfried_enabled=False, batch_size=300)
    archive = archives.add_archive("Disconnect", root)
    assert archive.id is not None
    disconnected_once = False

    def disconnect(progress: AuditProgress) -> None:
        nonlocal disconnected_once
        if progress.stage is AuditStage.PROCESSING and not disconnected_once:
            disconnected_once = True
            root.rename(disconnected)
            monkeypatch.setattr(
                "keepreadable.application.audit_service.is_root_available",
                lambda _path: False,
            )

    interrupted = engine.start(archive.id, AuditMode.DEEP, on_progress=disconnect)
    assert interrupted.status is AuditStatus.INTERRUPTED
    assert interrupted.interruption_reason == "archive_unavailable"
    with database.session() as session:
        assert not any(
            finding.code == FindingCode.FILE_MISSING
            for finding in FindingRepository(session).list(run_id=interrupted.id)
        )
        records = FileRecordRepository(session).list_present(archive.id, 0, 500)
        assert len(records) == 300
        assert all(record.present for record in records)
    disconnected.rename(root)
    monkeypatch.undo()
    resumed = engine.resume(interrupted.id or 0)
    assert resumed.status is AuditStatus.COMPLETED
    with database.session() as session:
        assert ObservationRepository(session).count_for_run(resumed.id or 0) == 300


def test_concurrency_smoke_has_exact_counts(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    root.mkdir()
    for index in range(500):
        (root / f"{index:03}.txt").write_text(f"value-{index}", encoding="utf-8")
    engine, archives, database = build_engine(
        tmp_path,
        siegfried_enabled=False,
        batch_size=100,
        worker_count=8,
        media_decode_workers=2,
    )
    archive = archives.add_archive("Concurrency", root)
    assert archive.id is not None
    run = engine.start(archive.id, AuditMode.DEEP)
    assert run.status is AuditStatus.COMPLETED
    assert run.files_processed == 500
    with database.session() as session:
        assert ObservationRepository(session).count_for_run(run.id or 0) == 500
        assert not any(
            finding.code == FindingCode.SCAN_ERROR
            for finding in FindingRepository(session).list(run_id=run.id)
        )


def test_cancel_is_final_and_new_run_allowed(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    root.mkdir()
    for index in range(100):
        (root / f"{index:03}.txt").write_text("x", encoding="utf-8")
    engine, archives, _database = build_engine(tmp_path, siegfried_enabled=False, batch_size=20)
    archive = archives.add_archive("Cancel", root)
    assert archive.id is not None
    token = CancellationToken()

    def cancel(progress: AuditProgress) -> None:
        if progress.stage is AuditStage.PROCESSING and progress.files_processed >= 20:
            token.cancel()

    stopped = engine.start(archive.id, AuditMode.QUICK, cancel=token, on_progress=cancel)
    assert stopped.status is AuditStatus.CANCELLED
    with pytest.raises(AuditStateError):
        engine.resume(stopped.id or 0)
    assert engine.start(archive.id, AuditMode.QUICK).status is AuditStatus.COMPLETED
