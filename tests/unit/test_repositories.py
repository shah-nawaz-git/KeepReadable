from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from keepreadable.domain.archive import Archive
from keepreadable.domain.audit import AuditRun
from keepreadable.domain.enums import (
    AuditMode,
    AuditStatus,
    ChangeKind,
    CheckStatus,
    CopyKind,
    FindingCategory,
    FindingSeverity,
    FindingState,
    HealthState,
    PolicyStatus,
    SupportTier,
    VerificationStatus,
)
from keepreadable.domain.file_record import FileRecord
from keepreadable.domain.finding import Finding
from keepreadable.domain.observation import Observation
from keepreadable.domain.preservation import GeneratedCopy
from keepreadable.persistence.database import Database
from keepreadable.persistence.models import (
    AuditRunModel,
    FileRecordModel,
    FindingModel,
    GeneratedCopyModel,
    ObservationModel,
)
from keepreadable.persistence.repositories import (
    ArchiveRepository,
    AuditRunRepository,
    FileRecordRepository,
    FindingRepository,
    GeneratedCopyRepository,
    ObservationRepository,
)

NOW = datetime(2026, 1, 2, 12, 0)


def make_archive(root_path: str = "C:/archive") -> Archive:
    return Archive(
        name="Personal archive",
        root_path=root_path,
        root_fingerprint="fingerprint",
        volume_serial=None,
        volume_label=None,
        created_at=NOW,
        last_seen_at=None,
    )


def make_run(
    archive_id: int,
    *,
    status: AuditStatus = AuditStatus.PENDING,
    mode: AuditMode = AuditMode.QUICK,
    started_at: datetime = NOW,
) -> AuditRun:
    return AuditRun(
        archive_id=archive_id,
        mode=mode,
        status=status,
        started_at=started_at,
        completed_at=None,
        policy_version="1",
        signature_version=None,
    )


def make_file(
    archive_id: int,
    run_id: int,
    path: str,
    *,
    size: int = 10,
    health: HealthState | None = None,
    verified_at: datetime | None = None,
) -> FileRecord:
    return FileRecord(
        archive_id=archive_id,
        relative_path=path,
        normalized_path=path.casefold().replace("\\", "/"),
        size=size,
        mtime_ns=123,
        filesystem_identity=None,
        first_seen_audit_id=run_id,
        last_seen_audit_id=run_id,
        present=True,
        last_health=health,
        last_deep_verified_at=verified_at,
        last_sha256=None,
    )


def make_observation(file_id: int, run_id: int, created_at: datetime = NOW) -> Observation:
    return Observation(
        file_record_id=file_id,
        audit_run_id=run_id,
        observed_size=10,
        observed_mtime_ns=123,
        sha256="a" * 64,
        hashed_at=created_at,
        extension=".txt",
        detected_format="Plain text",
        format_version=None,
        puid=None,
        mime_type="text/plain",
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
        created_at=created_at,
    )


def make_finding(
    run_id: int,
    file_id: int | None,
    severity: FindingSeverity = FindingSeverity.LOW,
    category: FindingCategory = FindingCategory.FORMAT_REVIEW,
) -> Finding:
    return Finding(
        file_record_id=file_id,
        audit_run_id=run_id,
        code="format_review",
        severity=severity,
        category=category,
        title="Review format",
        description="Evidence requires review.",
        created_at=NOW,
        resolved_at=None,
    )


def create_archive_and_run(db: Database) -> tuple[int, int]:
    with db.session() as session:
        archive = ArchiveRepository(session).add(make_archive())
        assert archive.id is not None
        run = AuditRunRepository(session).add(make_run(archive.id))
        assert run.id is not None
        return archive.id, run.id


def test_archive_create_get_list_and_delete_cascades(db: Database) -> None:
    with db.session() as session:
        archives = ArchiveRepository(session)
        archive = archives.add(make_archive())
        assert archive.id is not None
        assert archives.get(archive.id) == archive
        assert archives.list_active() == [archive]
        run = AuditRunRepository(session).add(make_run(archive.id))
        assert run.id is not None
        records = FileRecordRepository(session)
        file_id = records.upsert_batch(archive.id, [make_file(archive.id, run.id, "a.txt")])[0]
        ObservationRepository(session).add_batch([make_observation(file_id, run.id)])
        FindingRepository(session).add_batch([make_finding(run.id, file_id)])
        GeneratedCopyRepository(session).add(
            GeneratedCopy(
                source_file_record_id=file_id,
                output_path="C:/copies/a.pdf",
                copy_kind=CopyKind.ACCESS_COPY,
                operation="convert",
                created_at=NOW,
                source_hash="a" * 64,
                output_hash="b" * 64,
                verification_status=VerificationStatus.PASSED,
            )
        )
        assert archives.delete(archive.id)
    with db.session() as session:
        for model in (
            AuditRunModel,
            FileRecordModel,
            ObservationModel,
            FindingModel,
            GeneratedCopyModel,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_archive_deactivate_last_seen_and_fingerprint(db: Database) -> None:
    with db.session() as session:
        repository = ArchiveRepository(session)
        archive = repository.add(make_archive())
        assert archive.id is not None
        assert repository.find_by_fingerprint("fingerprint") == archive
        seen = NOW + timedelta(hours=1)
        updated = repository.update_last_seen(archive.id, seen)
        assert updated is not None
        assert updated.last_seen_at == seen
        assert repository.deactivate(archive.id)
        assert repository.list_active() == []


def test_audit_run_lifecycle_and_interrupted_lookup(db: Database) -> None:
    archive_id, _ = create_archive_and_run(db)
    with db.session() as session:
        repository = AuditRunRepository(session)
        pending = repository.latest_for_archive(archive_id)
        assert pending is not None
        assert pending.id is not None
        running = repository.update(
            pending.id,
            status=AuditStatus.RUNNING,
            files_discovered=3,
            resume_state={"cursor": "b.txt"},
        )
        assert running is not None
        assert running.status is AuditStatus.RUNNING
        assert repository.find_interrupted(archive_id) == [running]
        completed = repository.update(
            pending.id,
            status=AuditStatus.COMPLETED,
            completed_at=NOW + timedelta(minutes=1),
            files_processed=3,
        )
        assert completed is not None
        assert completed.status is AuditStatus.COMPLETED
        assert repository.find_interrupted(archive_id) == []
        assert repository.list_for_archive(archive_id) == [completed]


def test_file_upsert_updates_without_duplicate(db: Database) -> None:
    archive_id, run_id = create_archive_and_run(db)
    with db.session() as session:
        repository = FileRecordRepository(session)
        original = make_file(archive_id, run_id, "Folder/A.TXT", size=10)
        first_id = repository.upsert_batch(archive_id, [original])[0]
        updated = replace(original, size=99, mtime_ns=456)
        second_id = repository.upsert_batch(archive_id, [updated])[0]
        assert first_id == second_id
        result = repository.get_by_normalized_path(archive_id, original.normalized_path)
        assert result is not None
        assert result.size == 99
        assert result.mtime_ns == 456
        assert repository.totals(archive_id) == (1, 99)


def test_pending_records_exclude_observed_and_are_ordered(db: Database) -> None:
    archive_id, run_id = create_archive_and_run(db)
    with db.session() as session:
        records = FileRecordRepository(session)
        ids = records.upsert_batch(
            archive_id,
            [make_file(archive_id, run_id, "b.txt"), make_file(archive_id, run_id, "a.txt")],
        )
        ObservationRepository(session).add_batch([make_observation(ids[0], run_id)])
        pending = list(records.iter_pending_for_run(archive_id, run_id, batch_size=1))
        assert [record.normalized_path for record in pending] == ["a.txt"]
        assert records.count_pending_for_run(archive_id, run_id) == 1


def test_mark_missing_not_seen(db: Database) -> None:
    archive_id, first_run_id = create_archive_and_run(db)
    with db.session() as session:
        second_run = AuditRunRepository(session).add(
            make_run(archive_id, started_at=NOW + timedelta(days=1))
        )
        assert second_run.id is not None
        records = FileRecordRepository(session)
        records.upsert_batch(
            archive_id,
            [
                make_file(archive_id, first_run_id, "missing.txt"),
                make_file(archive_id, second_run.id, "present.txt"),
            ],
        )
        missing = records.mark_missing_not_seen(archive_id, second_run.id)
        assert [record.normalized_path for record in missing] == ["missing.txt"]
        stored = records.get_by_normalized_path(archive_id, "missing.txt")
        assert stored is not None
        assert not stored.present


def test_observations_are_preserved_and_ordered_newest_first(db: Database) -> None:
    archive_id, first_run_id = create_archive_and_run(db)
    with db.session() as session:
        runs = AuditRunRepository(session)
        second_run = runs.add(make_run(archive_id, started_at=NOW + timedelta(days=1)))
        assert second_run.id is not None
        records = FileRecordRepository(session)
        file_id = records.upsert_batch(archive_id, [make_file(archive_id, first_run_id, "a.txt")])[
            0
        ]
        observations = ObservationRepository(session)
        old = observations.add_batch([make_observation(file_id, first_run_id, NOW)])[0]
        new = observations.add_batch(
            [make_observation(file_id, second_run.id, NOW + timedelta(days=1))]
        )[0]
        assert observations.history_for_file(file_id) == [new, old]
        assert observations.latest_for_file(file_id) == new
        assert observations.count_for_run(first_run_id) == 1
        assert observations.count_for_run(second_run.id) == 1


def test_findings_filters_order_and_state_update(db: Database) -> None:
    archive_id, run_id = create_archive_and_run(db)
    with db.session() as session:
        file_id = FileRecordRepository(session).upsert_batch(
            archive_id, [make_file(archive_id, run_id, "a.txt")]
        )[0]
        repository = FindingRepository(session)
        low, high = repository.add_batch(
            [
                make_finding(run_id, file_id),
                make_finding(
                    run_id,
                    file_id,
                    FindingSeverity.HIGH,
                    FindingCategory.STRUCTURAL_WARNING,
                ),
            ]
        )
        assert repository.list(archive_id=archive_id) == [high, low]
        assert repository.list(category=FindingCategory.FORMAT_REVIEW) == [low]
        assert repository.counts_by_severity(archive_id) == {
            FindingSeverity.LOW: 1,
            FindingSeverity.HIGH: 1,
        }
        assert low.id is not None
        resolved = repository.update_state(low.id, FindingState.RESOLVED, NOW)
        assert resolved is not None
        assert resolved.state is FindingState.RESOLVED
        assert repository.open_for_file(file_id) == [high]


def test_generated_copy_relationship(db: Database) -> None:
    archive_id, run_id = create_archive_and_run(db)
    with db.session() as session:
        file_id = FileRecordRepository(session).upsert_batch(
            archive_id, [make_file(archive_id, run_id, "a.txt")]
        )[0]
        repository = GeneratedCopyRepository(session)
        generated = repository.add(
            GeneratedCopy(
                source_file_record_id=file_id,
                output_path="C:/copies/a.pdf",
                copy_kind=CopyKind.PRESERVATION_ORIENTED_COPY,
                operation="normalize",
                created_at=NOW,
                source_hash="a" * 64,
                output_hash=None,
                source_analysis={"format": "text"},
                output_analysis={},
                verification_status=VerificationStatus.LIMITED,
                verification_details={"reason": "visual review"},
                tool_versions={"converter": "1"},
            )
        )
        assert generated.id is not None
        assert repository.get(generated.id) == generated
        assert repository.list_for_file(file_id) == [generated]


def test_health_counts_deep_coverage_duplicate_lookup_and_listing(db: Database) -> None:
    archive_id, run_id = create_archive_and_run(db)
    recent = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5)
    old = recent - timedelta(days=400)
    with db.session() as session:
        repository = FileRecordRepository(session)
        records = [
            replace(
                make_file(
                    archive_id,
                    run_id,
                    "a.txt",
                    size=10,
                    health=HealthState.HEALTHY,
                    verified_at=recent,
                ),
                last_sha256="a" * 64,
            ),
            replace(
                make_file(
                    archive_id,
                    run_id,
                    "b.txt",
                    size=10,
                    health=HealthState.REVIEW,
                    verified_at=old,
                ),
                last_sha256="a" * 64,
            ),
            make_file(
                archive_id,
                run_id,
                "c.txt",
                size=20,
                health=HealthState.HEALTHY,
            ),
        ]
        repository.upsert_batch(archive_id, records)
        assert repository.health_counts(archive_id) == {
            HealthState.HEALTHY: 2,
            HealthState.REVIEW: 1,
        }
        assert repository.deep_verification_coverage(archive_id, 180) == (1, 3)
        duplicates = repository.find_by_sha256_and_size(archive_id, "a" * 64, 10)
        assert [item.normalized_path for item in duplicates] == ["a.txt", "b.txt"]
        assert [item.normalized_path for item in repository.list_present(archive_id)] == [
            "a.txt",
            "b.txt",
            "c.txt",
        ]
        assert [item.normalized_path for item in repository.search(archive_id, "B.TXT")] == [
            "b.txt"
        ]


def test_deleting_registration_does_not_touch_filesystem(db: Database, tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    original = archive_root / "original.txt"
    original.write_text("keep me", encoding="utf-8")
    with db.session() as session:
        repository = ArchiveRepository(session)
        archive = repository.add(make_archive(str(archive_root)))
        assert archive.id is not None
        assert repository.delete(archive.id)
    assert original.read_text(encoding="utf-8") == "keep me"
