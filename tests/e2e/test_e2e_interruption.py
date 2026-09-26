import shutil
from pathlib import Path

import pytest

from keepreadable.application.audit_service import AuditProgress, AuditStage
from keepreadable.application.container import AppContext
from keepreadable.config.settings import Settings
from keepreadable.domain.audit import AuditRun
from keepreadable.domain.enums import AuditMode, AuditStatus
from keepreadable.persistence.repositories import AuditRunRepository
from keepreadable.utilities.cancellation import CancellationToken
from scripts.create_demo_archive import create_demo_archive

pytestmark = pytest.mark.e2e


def health_and_hash(context: AppContext, archive_id: int) -> dict[str, tuple[object, str | None]]:
    return {
        record.relative_path: (record.last_health, record.last_sha256)
        for record in context.file_service.list_files(archive_id, 0, 10_000)
    }


def test_pause_restart_recovery_and_resume_matches_uninterrupted(tmp_path: Path) -> None:
    settings = Settings(
        worker_count=8,
        persistence_batch_size=200,
        identification_batch_size=200,
    )
    root = tmp_path / "paused-demo"
    create_demo_archive(root, seed=91, media=False, large=2000)
    fresh_root = tmp_path / "fresh-demo"
    shutil.copytree(root, fresh_root)
    data_dir = tmp_path / "paused-data"
    context = AppContext.create(data_dir, settings)
    archive = context.archive_service.add_archive("Paused Demo", root)
    assert archive.id is not None
    token = CancellationToken()

    def pause(progress: AuditProgress) -> None:
        total = progress.files_total_estimate
        if (
            progress.stage is AuditStage.PROCESSING
            and total
            and progress.files_processed / total >= 0.4
        ):
            token.cancel("pause")

    paused = context.audit_engine.start(
        archive.id,
        AuditMode.DEEP,
        cancel=token,
        on_progress=pause,
    )
    assert paused.status is AuditStatus.PAUSED
    context.db.dispose()

    restarted = AppContext.create(data_dir, settings)
    assert restarted.audit_engine.recover_interrupted() == []
    resumed = restarted.audit_engine.resume(paused.id or 0)
    assert resumed.status is AuditStatus.COMPLETED

    with restarted.db.session() as session:
        dummy = AuditRunRepository(session).add(
            AuditRun(
                archive_id=archive.id,
                mode=AuditMode.QUICK,
                status=AuditStatus.RUNNING,
                started_at=resumed.completed_at or resumed.started_at,
                completed_at=None,
                policy_version="1.0",
                signature_version=None,
            )
        )
    recovered = restarted.audit_engine.recover_interrupted()
    assert [run.id for run in recovered] == [dummy.id]
    assert recovered[0].status is AuditStatus.INTERRUPTED

    fresh = AppContext.create(tmp_path / "fresh-data", settings)
    fresh_archive = fresh.archive_service.add_archive("Fresh Demo", fresh_root)
    assert fresh_archive.id is not None
    uninterrupted = fresh.audit_engine.start(fresh_archive.id, AuditMode.DEEP)
    assert uninterrupted.status is AuditStatus.COMPLETED
    assert health_and_hash(restarted, archive.id) == health_and_hash(fresh, fresh_archive.id)
