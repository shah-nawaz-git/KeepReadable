from collections.abc import Callable
from pathlib import Path

import pytest

from keepreadable.application.container import AppContext
from keepreadable.config.settings import Settings
from keepreadable.domain.enums import AuditMode, AuditStatus, VerificationStatus
from keepreadable.domain.preservation import CopyOperation
from tests.fixture_factory import assert_unchanged, make_avi, make_mov

pytestmark = pytest.mark.external_tools


@pytest.mark.parametrize(
    ("factory", "operation"),
    [
        (make_avi, CopyOperation.VIDEO_TO_MP4),
        (make_mov, CopyOperation.VIDEO_TO_MP4),
    ],
)
def test_real_video_compatibility_copy(
    tmp_path: Path, factory: Callable[..., Path], operation: CopyOperation
) -> None:
    context = AppContext.create(
        tmp_path / "data",
        Settings(worker_count=2, persistence_batch_size=10, identification_batch_size=10),
    )
    if context.ffmpeg is None:
        pytest.skip("FFmpeg is unavailable")
    root = tmp_path / "archive"
    root.mkdir()
    source = factory(root / f"source.{factory.__name__.removeprefix('make_')}")
    archive = context.archive_service.add_archive("Video", root)
    assert archive.id is not None
    run = context.audit_engine.start(archive.id, AuditMode.DEEP)
    assert run.status is AuditStatus.COMPLETED
    record = context.file_service.list_files(archive.id, 0, 10)[0]
    assert record.id is not None
    proposal = context.preservation_service.propose(record.id, operation)
    with assert_unchanged(source):
        result = context.preservation_service.execute(proposal)
    assert result.verification_status is VerificationStatus.PASSED
    assert result.output_path is not None
    assert Path(result.output_path).is_file()
    assert context.ffmpeg.decode_to_null(Path(result.output_path)).success
    assert context.preservation_service.list_copies(record.id)[0].id == result.id
