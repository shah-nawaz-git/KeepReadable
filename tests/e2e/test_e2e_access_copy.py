import hashlib
from pathlib import Path

import pytest

from keepreadable.application.container import AppContext
from keepreadable.config.settings import Settings
from keepreadable.domain.enums import AuditMode, AuditStatus, VerificationStatus
from keepreadable.domain.preservation import CopyOperation
from scripts.create_demo_archive import create_demo_archive

pytestmark = [pytest.mark.e2e, pytest.mark.external_tools]


def test_demo_avi_access_copy_is_verified_and_reported(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    manifest = create_demo_archive(root, seed=33, media=True)
    if not manifest["media_included"]:
        pytest.skip("FFmpeg is unavailable")
    context = AppContext.create(
        tmp_path / "data",
        Settings(worker_count=4, persistence_batch_size=100, identification_batch_size=100),
    )
    archive = context.archive_service.add_archive("Copy Demo", root)
    assert archive.id is not None
    run = context.audit_engine.start(archive.id, AuditMode.DEEP)
    assert run.status is AuditStatus.COMPLETED
    record = next(
        item
        for item in context.file_service.list_files(archive.id, 0, 1000)
        if item.relative_path.endswith("old-camera.avi")
    )
    assert record.id is not None
    source = root / record.relative_path
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = context.preservation_service.execute(
        context.preservation_service.propose(
            record.id,
            CopyOperation.VIDEO_TO_MP4,
            destination_dir=tmp_path / "copies",
        )
    )
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert result.verification_status is VerificationStatus.PASSED
    detail = context.file_service.file_detail(record.id)
    assert any(copy.id == result.id for copy in detail.generated_copies)
    report = context.report_service.build(run.id or 0)
    assert any(
        copy.operation == CopyOperation.VIDEO_TO_MP4.value for copy in report.generated_copies
    )
