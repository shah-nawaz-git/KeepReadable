import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from keepreadable.application.preservation_service import (
    CopyError,
    InsufficientSpaceError,
    PreservationService,
    SourceChangedError,
)
from keepreadable.config.settings import Settings
from keepreadable.domain.archive import Archive
from keepreadable.domain.audit import AuditRun
from keepreadable.domain.enums import (
    AuditMode,
    AuditStatus,
    ChangeKind,
    CheckStatus,
    HealthState,
    PolicyStatus,
    SupportTier,
    VerificationStatus,
)
from keepreadable.domain.file_record import FileRecord
from keepreadable.domain.observation import Observation
from keepreadable.domain.preservation import CopyOperation
from keepreadable.integrations.ffmpeg import DecodeResult, ProbeResult, StreamInfo
from keepreadable.integrations.subprocess_runner import CommandResult
from keepreadable.persistence.database import Database
from keepreadable.persistence.repositories import (
    ArchiveRepository,
    AuditRunRepository,
    FileRecordRepository,
    ObservationRepository,
)
from keepreadable.utilities.cancellation import OperationCancelled
from keepreadable.validators.registry import ValidatorRegistry
from tests.fixture_factory import assert_unchanged, make_bmp

NOW = datetime(2026, 9, 26, 12)


class FakeFFmpeg:
    def __init__(
        self,
        *,
        output_audio: bool = True,
        source_duration: float | None = 1.0,
        output_duration: float | None = 1.0,
        fail: bool = False,
        cancel: bool = False,
        source_to_touch: Path | None = None,
    ) -> None:
        self.ffmpeg = Path("ffmpeg.exe")
        self.ffprobe = Path("ffprobe.exe")
        self.output_audio = output_audio
        self.source_duration = source_duration
        self.output_duration = output_duration
        self.fail = fail
        self.cancel = cancel
        self.source_to_touch = source_to_touch

    def version(self) -> str:
        return "test"

    def probe(self, path: Path, *, cancel: object = None) -> ProbeResult:
        output = path.suffix.casefold() == ".mp4"
        duration = self.output_duration if output else self.source_duration
        streams = [
            StreamInfo(
                0,
                "video",
                "h264" if output else "mpeg4",
                None,
                64,
                64,
                "10/1",
                "10/1",
                None,
                None,
                duration,
                None,
                10,
                "yuv420p",
            )
        ]
        if not output or self.output_audio:
            streams.append(
                StreamInfo(
                    1,
                    "audio",
                    "aac" if output else "mp3",
                    None,
                    None,
                    None,
                    None,
                    None,
                    44100,
                    1,
                    duration,
                    None,
                    None,
                    None,
                )
            )
        return ProbeResult(
            "mp4" if output else "avi", None, duration, 100, None, tuple(streams), ()
        )

    def decode_to_null(self, path: Path, *, cancel: object = None) -> DecodeResult:
        return DecodeResult(True, 0, (), 0.1, False)

    def run(
        self,
        args: list[str],
        *,
        cancel: object = None,
        timeout: float | None = None,
    ) -> CommandResult:
        if self.cancel:
            raise OperationCancelled
        if self.source_to_touch is not None:
            stat = self.source_to_touch.stat()
            os.utime(
                self.source_to_touch,
                ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000),
            )
        output = Path(args[-1])
        if not self.fail:
            output.write_bytes(b"synthetic mp4")
        return CommandResult(tuple(args), 1 if self.fail else 0, b"", b"failure", 0.1, False)


def registered_file(
    tmp_path: Path,
    *,
    extension: str,
    puid: str,
    detected_format: str,
) -> tuple[Database, int, Path]:
    root = tmp_path / "archive"
    root.mkdir()
    path = root / f"source.{extension}"
    if extension == "bmp":
        make_bmp(path)
    else:
        path.write_bytes(b"synthetic source media")
    database = Database(tmp_path / "database.db")
    database.initialize()
    with database.session() as session:
        archive = ArchiveRepository(session).add(
            Archive(
                name="Archive",
                root_path=str(root),
                root_fingerprint="fingerprint",
                volume_serial=None,
                volume_label=None,
                created_at=NOW,
                last_seen_at=None,
            )
        )
        assert archive.id is not None
        run = AuditRunRepository(session).add(
            AuditRun(
                archive_id=archive.id,
                mode=AuditMode.DEEP,
                status=AuditStatus.COMPLETED,
                started_at=NOW,
                completed_at=NOW,
                policy_version="1",
                signature_version="sig",
            )
        )
        assert run.id is not None
        record_id = FileRecordRepository(session).upsert_batch(
            archive.id,
            [
                FileRecord(
                    archive_id=archive.id,
                    relative_path=path.name,
                    normalized_path=path.name,
                    size=path.stat().st_size,
                    mtime_ns=path.stat().st_mtime_ns,
                    filesystem_identity=None,
                    first_seen_audit_id=run.id,
                    last_seen_audit_id=run.id,
                    present=True,
                    last_health=HealthState.HEALTHY,
                    last_deep_verified_at=NOW,
                    last_sha256=None,
                    last_format=detected_format,
                )
            ],
        )[0]
        ObservationRepository(session).add_batch(
            [
                Observation(
                    file_record_id=record_id,
                    audit_run_id=run.id,
                    observed_size=path.stat().st_size,
                    observed_mtime_ns=path.stat().st_mtime_ns,
                    sha256=None,
                    hashed_at=None,
                    extension=extension,
                    detected_format=detected_format,
                    format_version=None,
                    puid=puid,
                    mime_type=None,
                    extension_matches_signature=True,
                    identification_warning=None,
                    structural_status=CheckStatus.PASSED,
                    readability_status=CheckStatus.PASSED,
                    policy_status=PolicyStatus.NORMAL,
                    policy_reason=None,
                    health=HealthState.HEALTHY,
                    change_kind=ChangeKind.NEW,
                    validator_name="test",
                    validator_version="1",
                    support_tier=SupportTier.DEEP,
                    validation_details={"duration_seconds": 1.0},
                    created_at=NOW,
                )
            ]
        )
    return database, record_id, path


def service(database: Database, ffmpeg: FakeFFmpeg | None = None) -> PreservationService:
    return PreservationService(
        database,
        Settings(),
        ffmpeg=ffmpeg,
        validators=ValidatorRegistry(ffmpeg=ffmpeg),  # type: ignore[arg-type]
    )


def test_bmp_to_png_passes_pixel_equality_and_conflict_naming(tmp_path: Path) -> None:
    database, record_id, source = registered_file(
        tmp_path, extension="bmp", puid="fmt/114", detected_format="Windows Bitmap"
    )
    copies = service(database)
    (source.parent / "source.access.png").write_bytes(b"existing")
    proposal = copies.propose(record_id, CopyOperation.BMP_TO_PNG)
    assert proposal.proposed_output_name == "source.access-2.png"
    with assert_unchanged(source):
        result = copies.execute(proposal)
    assert result.verification_status is VerificationStatus.PASSED
    assert result.output_path is not None
    assert Path(result.output_path).name == "source.access-2.png"
    assert result.verification_details["lossless_pixel_equality"] is True
    assert len(copies.list_copies(record_id)) == 1


def test_insufficient_space_and_source_destination_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, record_id, source = registered_file(
        tmp_path, extension="bmp", puid="fmt/114", detected_format="Windows Bitmap"
    )
    copies = service(database)
    proposal = copies.propose(record_id, CopyOperation.BMP_TO_PNG)
    monkeypatch.setattr(
        "keepreadable.application.preservation_service.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=0),
    )
    with assert_unchanged(source), pytest.raises(InsufficientSpaceError):
        copies.execute(proposal)
    assert not list(source.parent.glob(".keepreadable-tmp-*"))
    destination_file = tmp_path / "destination-file"
    destination_file.write_text("not a directory", encoding="utf-8")
    bad_destination = replace(
        proposal,
        destination_dir=destination_file,
        proposed_output_name="copy.png",
    )
    with assert_unchanged(source), pytest.raises(CopyError):
        copies.execute(bad_destination)
    guarded = replace(proposal, proposed_output_name=source.name)
    with assert_unchanged(source), pytest.raises(CopyError, match="cannot be the source"):
        copies.execute(guarded)


def test_corrupt_output_is_failed_and_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, record_id, source = registered_file(
        tmp_path, extension="bmp", puid="fmt/114", detected_format="Windows Bitmap"
    )
    copies = service(database)
    original_analyze = copies._analyze

    def damage_then_analyze(path: Path, operation: CopyOperation, cancel: object) -> Any:
        if path.name.startswith(".keepreadable-tmp-"):
            path.write_bytes(b"not a PNG")
        return original_analyze(path, operation, cancel)

    monkeypatch.setattr(copies, "_analyze", damage_then_analyze)
    with assert_unchanged(source):
        result = copies.execute(copies.propose(record_id, CopyOperation.BMP_TO_PNG))
    assert result.verification_status is VerificationStatus.FAILED
    assert result.output_path is None
    assert not list(source.parent.glob(".keepreadable-tmp-*"))


def test_video_failure_mismatch_limited_cancel_and_source_change(tmp_path: Path) -> None:
    database, record_id, source = registered_file(
        tmp_path, extension="avi", puid="fmt/5", detected_format="AVI"
    )
    failed_service = service(database, FakeFFmpeg(fail=True))
    proposal = failed_service.propose(record_id, CopyOperation.VIDEO_TO_MP4)
    with assert_unchanged(source), pytest.raises(CopyError):
        failed_service.execute(proposal)
    assert failed_service.list_copies(record_id)[0].verification_status is VerificationStatus.FAILED
    assert not list(source.parent.glob(".keepreadable-tmp-*"))

    missing_audio = service(database, FakeFFmpeg(output_audio=False))
    with assert_unchanged(source):
        mismatch = missing_audio.execute(
            missing_audio.propose(record_id, CopyOperation.VIDEO_TO_MP4)
        )
    assert mismatch.verification_status is VerificationStatus.FAILED
    assert any(
        item["name"] == "audio presence" and not item["passed"]
        for item in mismatch.verification_details["comparisons"]
    )

    duration = service(database, FakeFFmpeg(output_duration=4.0))
    with assert_unchanged(source):
        mismatch = duration.execute(duration.propose(record_id, CopyOperation.VIDEO_TO_MP4))
    assert mismatch.verification_status is VerificationStatus.FAILED

    limited_service = service(database, FakeFFmpeg(source_duration=None, output_duration=None))
    with assert_unchanged(source):
        limited = limited_service.execute(
            limited_service.propose(record_id, CopyOperation.VIDEO_TO_MP4)
        )
    assert limited.verification_status is VerificationStatus.LIMITED
    assert "duration comparison" in limited.verification_details["checks_not_performed"]

    cancelled_service = service(database, FakeFFmpeg(cancel=True))
    with assert_unchanged(source), pytest.raises(OperationCancelled):
        cancelled_service.execute(cancelled_service.propose(record_id, CopyOperation.VIDEO_TO_MP4))
    assert (
        cancelled_service.list_copies(record_id)[0].verification_details["failure_reason"]
        == "cancelled"
    )

    changed_service = service(database, FakeFFmpeg(source_to_touch=source))
    with assert_unchanged(source), pytest.raises(SourceChangedError):
        changed_service.execute(changed_service.propose(record_id, CopyOperation.VIDEO_TO_MP4))
