from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from keepreadable.application.container import AppContext
from keepreadable.config.settings import Settings
from keepreadable.domain.enums import AuditMode, AuditStatus, FindingCode
from keepreadable.integrations.siegfried import SiegfriedInfo, SiegfriedOutputError
from keepreadable.persistence.repositories import (
    FileRecordRepository,
    FindingRepository,
    ObservationRepository,
)


def make_context(tmp_path: Path) -> AppContext:
    return AppContext.create(
        tmp_path / "data",
        Settings(worker_count=1, persistence_batch_size=10, identification_batch_size=10),
    )


class MalformedSiegfried:
    @staticmethod
    def info() -> SiegfriedInfo:
        return SiegfriedInfo("test", "default.sig", None, "test signatures")

    @staticmethod
    def identify(*_args: object, **_kwargs: object) -> object:
        raise SiegfriedOutputError("malformed output")


def test_malformed_identification_output_does_not_stop_audit(tmp_path: Path) -> None:
    root = tmp_path / "malformed-tool"
    root.mkdir()
    (root / "image.jpg").write_bytes(b"not an image")
    context = make_context(tmp_path)
    context.audit_engine.siegfried = MalformedSiegfried()
    archive = context.archive_service.add_archive("Malformed Tool", root)
    assert archive.id is not None
    run = context.audit_engine.start(archive.id, AuditMode.QUICK)
    assert run.status is AuditStatus.COMPLETED
    record = context.file_service.list_files(archive.id, 0, 10)[0]
    with context.db.session() as session:
        observation = ObservationRepository(session).latest_for_file(record.id or 0)
        assert observation is not None
        assert observation.identification_warning == "identification tool unavailable"


def test_empty_archive_completes_without_findings(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    context = make_context(tmp_path)
    archive = context.archive_service.add_archive("Empty", root)
    assert archive.id is not None
    run = context.audit_engine.start(archive.id, AuditMode.DEEP)
    assert run.status is AuditStatus.COMPLETED
    assert run.files_processed == 0
    overview = context.archive_service.overview(archive.id)
    assert overview.file_count == 0
    assert overview.top_findings == []


@pytest.mark.skipif(os.name != "nt", reason="Windows byte-range locking test")
def test_locked_file_becomes_scan_error_not_run_failure(tmp_path: Path) -> None:
    msvcrt = pytest.importorskip("msvcrt")
    root = tmp_path / "archive"
    root.mkdir()
    path = root / "locked.bin"
    path.write_bytes(b"locked content")
    context = make_context(tmp_path)
    archive = context.archive_service.add_archive("Locked", root)
    assert archive.id is not None
    with path.open("r+b") as locked:
        msvcrt.locking(locked.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            run = context.audit_engine.start(archive.id, AuditMode.DEEP)
        finally:
            locked.seek(0)
            msvcrt.locking(locked.fileno(), msvcrt.LK_UNLCK, 1)
    assert run.status is AuditStatus.COMPLETED
    assert run.files_failed == 1
    with context.db.session() as session:
        assert any(
            finding.code == FindingCode.SCAN_ERROR.value
            for finding in FindingRepository(session).list(run_id=run.id)
        )


def test_deleted_between_discovery_and_processing_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "archive"
    root.mkdir()
    path = root / "vanishing.txt"
    path.write_text("temporary", encoding="utf-8")
    context = make_context(tmp_path)
    archive = context.archive_service.add_archive("Vanishing", root)
    assert archive.id is not None
    original = context.audit_engine._work_one
    deleted = False

    def remove_then_work(*args: Any, **kwargs: Any):
        nonlocal deleted
        if not deleted:
            deleted = True
            path.unlink()
        return original(*args, **kwargs)

    monkeypatch.setattr(context.audit_engine, "_work_one", remove_then_work)
    run = context.audit_engine.start(archive.id, AuditMode.DEEP)
    assert run.status is AuditStatus.COMPLETED
    assert run.files_failed == 1
    with context.db.session() as session:
        record = FileRecordRepository(session).get_by_normalized_path(archive.id, "vanishing.txt")
        assert record is not None
        assert any(
            finding.code == FindingCode.SCAN_ERROR.value
            for finding in FindingRepository(session).list(run_id=run.id)
        )
