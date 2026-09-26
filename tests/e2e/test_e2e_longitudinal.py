import os
from pathlib import Path

import pytest

from keepreadable.application.container import AppContext
from keepreadable.config.settings import Settings
from keepreadable.domain.enums import AuditMode, AuditStatus, FindingCode, FindingSeverity
from keepreadable.persistence.repositories import FindingRepository, ObservationRepository
from scripts.create_demo_archive import create_demo_archive

pytestmark = [pytest.mark.e2e, pytest.mark.external_tools]


def test_demo_archive_longitudinal_history(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    create_demo_archive(root, seed=17, media=False)
    context = AppContext.create(
        tmp_path / "data",
        Settings(worker_count=8, persistence_batch_size=100, identification_batch_size=100),
    )
    archive = context.archive_service.add_archive("Longitudinal Demo", root)
    assert archive.id is not None
    first = context.audit_engine.start(archive.id, AuditMode.DEEP)
    assert first.status is AuditStatus.COMPLETED

    modified = root / "Documents" / "University" / "note-000.txt"
    modified.write_text("Visible edit with changed metadata.\n", encoding="utf-8")
    silent = root / "Documents" / "University" / "note-001.txt"
    original = silent.stat()
    original_bytes = silent.read_bytes()
    replacement = bytes((value + 1) % 256 for value in original_bytes)
    silent.write_bytes(replacement)
    os.utime(silent, ns=(original.st_atime_ns, original.st_mtime_ns))
    deleted = root / "Documents" / "University" / "note-002.txt"
    deleted.unlink()
    moved = root / "Documents" / "University" / "note-003.txt"
    moved.rename(root / "Documents" / "Scans" / "moved-note.txt")
    (root / "Documents" / "University" / "new-note.txt").write_text(
        "New synthetic note.\n", encoding="utf-8"
    )

    second = context.audit_engine.start(archive.id, AuditMode.DEEP, force_deep_all=True)
    third = context.audit_engine.start(archive.id, AuditMode.DEEP)
    assert second.status is AuditStatus.COMPLETED
    assert third.status is AuditStatus.COMPLETED
    records = context.file_service.list_files(archive.id, 0, 10_000)
    modified_record = next(
        record for record in records if record.relative_path.endswith("note-000.txt")
    )
    detail = context.file_service.file_detail(modified_record.id or 0)
    assert len(detail.history) == 3
    assert all(observation.health is not None for observation in detail.history)

    with context.db.session() as session:
        findings = FindingRepository(session).list(run_id=second.id)
    integrity = [
        finding for finding in findings if finding.code == FindingCode.INTEGRITY_MISMATCH.value
    ]
    assert {finding.severity for finding in integrity} == {
        FindingSeverity.MEDIUM,
        FindingSeverity.HIGH,
    }
    missing = [finding for finding in findings if finding.code == FindingCode.FILE_MISSING.value]
    assert {finding.severity for finding in missing} == {
        FindingSeverity.MEDIUM,
        FindingSeverity.INFO,
    }
    with context.db.session() as session:
        assert ObservationRepository(session).count_for_run(third.id or 0) == len(records)
