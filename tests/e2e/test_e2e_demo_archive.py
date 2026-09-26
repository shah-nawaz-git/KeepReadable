from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from keepreadable.application.container import AppContext
from keepreadable.config.settings import Settings
from keepreadable.domain.enums import AuditMode, AuditStatus, FindingCode, FindingSeverity
from keepreadable.persistence.repositories import FindingRepository, ObservationRepository
from scripts.create_demo_archive import create_demo_archive
from tests.fixture_factory import ffmpeg_available

pytestmark = [pytest.mark.e2e, pytest.mark.external_tools]


def snapshot_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_demo_archive_quick_deep_and_incremental(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    manifest = create_demo_archive(
        root,
        seed=42,
        media=ffmpeg_available(),
        manifest=True,
    )
    before = snapshot_hashes(root)
    context = AppContext.create(
        tmp_path / "data",
        Settings(worker_count=8, persistence_batch_size=100, identification_batch_size=100),
    )
    archive = context.archive_service.add_archive("Family Archive", root)
    assert archive.id is not None
    quick = context.audit_engine.start(archive.id, AuditMode.QUICK)
    deep = context.audit_engine.start(archive.id, AuditMode.DEEP)
    assert quick.status is AuditStatus.COMPLETED
    assert deep.status is AuditStatus.COMPLETED
    assert snapshot_hashes(root) == before

    records = context.file_service.list_files(archive.id, 0, 10_000)
    health = {
        record.relative_path: record.last_health.value if record.last_health else None
        for record in records
    }
    expected = manifest["expected_outcomes"]
    assert isinstance(expected, dict)
    for relative_path, outcome in expected.items():
        assert health[relative_path] == outcome["health"], relative_path

    displays = context.findings_service.list_findings(archive_id=archive.id, limit=10_000)
    codes_by_path: dict[str, set[str]] = {}
    for display in displays:
        if display.relative_path:
            codes_by_path.setdefault(display.relative_path, set()).add(display.finding.code)
    for relative_path, outcome in expected.items():
        for code in outcome["finding_codes"]:
            assert code in codes_by_path.get(relative_path, set()), relative_path
    assert (
        FindingCode.EXTENSION_MISMATCH.value
        in codes_by_path["Downloads/image-with-wrong-extension.jpg"]
    )
    assert health["Downloads/mystery"] == "unknown"
    for protected in (
        "Documents/University/protected-notes.pdf",
        "Downloads/protected-package.zip",
    ):
        assert health[protected] == "review"
        assert FindingCode.PROTECTED_CONTENT.value in codes_by_path[protected]
    assert health["Documents/University/missing-main.docx"] == "unreadable"
    if manifest["media_included"]:
        assert health["Video/truncated-video.mp4"] == "unreadable"
    duplicate_findings = [
        display.finding
        for display in displays
        if display.finding.code == FindingCode.DUPLICATE_CONTENT.value
    ]
    assert len(duplicate_findings) == 1
    assert duplicate_findings[0].severity is FindingSeverity.INFO

    with context.db.session() as session:
        observations = ObservationRepository(session)
        assert observations.count_for_run(quick.id or 0) == len(records)
        assert observations.count_for_run(deep.id or 0) == len(records)
        finding_ids = {
            finding.id for finding in FindingRepository(session).latest_findings(archive.id)
        }
    second = context.audit_engine.start(archive.id, AuditMode.DEEP)
    assert second.status is AuditStatus.COMPLETED
    with context.db.session() as session:
        assert ObservationRepository(session).count_for_run(second.id or 0) == len(records)
        assert {
            finding.id for finding in FindingRepository(session).latest_findings(archive.id)
        } == finding_ids
    assert snapshot_hashes(root) == before
