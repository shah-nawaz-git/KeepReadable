from __future__ import annotations

import builtins
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

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
from keepreadable.persistence.models import (
    ArchiveModel,
    AuditRunModel,
    FileRecordModel,
    FindingModel,
    GeneratedCopyModel,
    ObservationModel,
)
from keepreadable.utilities.clock import utcnow


def _archive(model: ArchiveModel) -> Archive:
    return Archive(
        id=model.id,
        name=model.name,
        root_path=model.root_path,
        root_fingerprint=model.root_fingerprint,
        volume_serial=model.volume_serial,
        volume_label=model.volume_label,
        created_at=model.created_at,
        last_seen_at=model.last_seen_at,
        active=model.active,
    )


def _audit(model: AuditRunModel) -> AuditRun:
    return AuditRun(
        id=model.id,
        archive_id=model.archive_id,
        mode=AuditMode(model.mode),
        status=AuditStatus(model.status),
        started_at=model.started_at,
        completed_at=model.completed_at,
        policy_version=model.policy_version,
        signature_version=model.signature_version,
        tool_versions=dict(model.tool_versions),
        files_discovered=model.files_discovered,
        files_processed=model.files_processed,
        files_failed=model.files_failed,
        files_skipped=model.files_skipped,
        findings_count=model.findings_count,
        error_summary=model.error_summary,
        resume_state=dict(model.resume_state),
        force_deep_all=model.force_deep_all,
        interruption_reason=model.interruption_reason,
    )


def _file_record(model: FileRecordModel) -> FileRecord:
    return FileRecord(
        id=model.id,
        archive_id=model.archive_id,
        relative_path=model.relative_path,
        normalized_path=model.normalized_path,
        size=model.size,
        mtime_ns=model.mtime_ns,
        filesystem_identity=model.filesystem_identity,
        first_seen_audit_id=model.first_seen_audit_id,
        last_seen_audit_id=model.last_seen_audit_id,
        present=model.present,
        last_health=HealthState(model.last_health) if model.last_health else None,
        last_deep_verified_at=model.last_deep_verified_at,
        last_sha256=model.last_sha256,
    )


def _observation(model: ObservationModel) -> Observation:
    return Observation(
        id=model.id,
        file_record_id=model.file_record_id,
        audit_run_id=model.audit_run_id,
        observed_size=model.observed_size,
        observed_mtime_ns=model.observed_mtime_ns,
        sha256=model.sha256,
        hashed_at=model.hashed_at,
        extension=model.extension,
        detected_format=model.detected_format,
        format_version=model.format_version,
        puid=model.puid,
        mime_type=model.mime_type,
        extension_matches_signature=model.extension_matches_signature,
        identification_warning=model.identification_warning,
        structural_status=CheckStatus(model.structural_status),
        readability_status=CheckStatus(model.readability_status),
        policy_status=PolicyStatus(model.policy_status),
        policy_reason=model.policy_reason,
        health=HealthState(model.health),
        change_kind=ChangeKind(model.change_kind),
        validator_name=model.validator_name,
        validator_version=model.validator_version,
        support_tier=SupportTier(model.support_tier),
        validation_details=dict(model.validation_details),
        created_at=model.created_at,
    )


def _finding(model: FindingModel) -> Finding:
    return Finding(
        id=model.id,
        file_record_id=model.file_record_id,
        audit_run_id=model.audit_run_id,
        code=model.code,
        severity=FindingSeverity(model.severity),
        category=FindingCategory(model.category),
        title=model.title,
        description=model.description,
        evidence=dict(model.evidence),
        state=FindingState(model.state),
        created_at=model.created_at,
        resolved_at=model.resolved_at,
    )


def _generated_copy(model: GeneratedCopyModel) -> GeneratedCopy:
    return GeneratedCopy(
        id=model.id,
        source_file_record_id=model.source_file_record_id,
        output_path=model.output_path,
        copy_kind=CopyKind(model.copy_kind),
        operation=model.operation,
        created_at=model.created_at,
        source_hash=model.source_hash,
        output_hash=model.output_hash,
        source_analysis=dict(model.source_analysis),
        output_analysis=dict(model.output_analysis),
        verification_status=VerificationStatus(model.verification_status),
        verification_details=dict(model.verification_details),
        tool_versions=dict(model.tool_versions),
    )


class ArchiveRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, archive: Archive) -> Archive:
        model = ArchiveModel(
            name=archive.name,
            root_path=archive.root_path,
            root_fingerprint=archive.root_fingerprint,
            volume_serial=archive.volume_serial,
            volume_label=archive.volume_label,
            created_at=archive.created_at,
            last_seen_at=archive.last_seen_at,
            active=archive.active,
        )
        self.session.add(model)
        self.session.flush()
        return _archive(model)

    def get(self, archive_id: int) -> Archive | None:
        model = self.session.get(ArchiveModel, archive_id)
        return _archive(model) if model else None

    def list_active(self) -> list[Archive]:
        models = self.session.scalars(
            select(ArchiveModel).where(ArchiveModel.active).order_by(ArchiveModel.name)
        )
        return [_archive(model) for model in models]

    def update_last_seen(self, archive_id: int, last_seen_at: datetime) -> Archive | None:
        model = self.session.get(ArchiveModel, archive_id)
        if model is None:
            return None
        model.last_seen_at = last_seen_at
        model.active = True
        self.session.flush()
        return _archive(model)

    def deactivate(self, archive_id: int) -> bool:
        model = self.session.get(ArchiveModel, archive_id)
        if model is None:
            return False
        model.active = False
        self.session.flush()
        return True

    def delete(self, archive_id: int) -> bool:
        model = self.session.get(ArchiveModel, archive_id)
        if model is None:
            return False
        self.session.delete(model)
        self.session.flush()
        return True

    def find_by_fingerprint(self, fingerprint: str) -> Archive | None:
        model = self.session.scalar(
            select(ArchiveModel).where(ArchiveModel.root_fingerprint == fingerprint)
        )
        return _archive(model) if model else None


class AuditRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, run: AuditRun) -> AuditRun:
        model = AuditRunModel(
            archive_id=run.archive_id,
            mode=run.mode.value,
            status=run.status.value,
            started_at=run.started_at,
            completed_at=run.completed_at,
            policy_version=run.policy_version,
            signature_version=run.signature_version,
            tool_versions=run.tool_versions,
            files_discovered=run.files_discovered,
            files_processed=run.files_processed,
            files_failed=run.files_failed,
            files_skipped=run.files_skipped,
            findings_count=run.findings_count,
            error_summary=run.error_summary,
            resume_state=run.resume_state,
            force_deep_all=run.force_deep_all,
            interruption_reason=run.interruption_reason,
        )
        self.session.add(model)
        self.session.flush()
        return _audit(model)

    def get(self, run_id: int) -> AuditRun | None:
        model = self.session.get(AuditRunModel, run_id)
        return _audit(model) if model else None

    def update(
        self,
        run_id: int,
        *,
        status: AuditStatus | None = None,
        completed_at: datetime | None = None,
        files_discovered: int | None = None,
        files_processed: int | None = None,
        files_failed: int | None = None,
        files_skipped: int | None = None,
        findings_count: int | None = None,
        resume_state: dict[str, Any] | None = None,
        error_summary: str | None = None,
        interruption_reason: str | None = None,
    ) -> AuditRun | None:
        model = self.session.get(AuditRunModel, run_id)
        if model is None:
            return None
        values: dict[str, Any] = {
            "status": status.value if status else None,
            "completed_at": completed_at,
            "files_discovered": files_discovered,
            "files_processed": files_processed,
            "files_failed": files_failed,
            "files_skipped": files_skipped,
            "findings_count": findings_count,
            "resume_state": resume_state,
            "error_summary": error_summary,
            "interruption_reason": interruption_reason,
        }
        for name, value in values.items():
            if value is not None:
                setattr(model, name, value)
        self.session.flush()
        return _audit(model)

    def latest_for_archive(self, archive_id: int, mode: AuditMode | None = None) -> AuditRun | None:
        statement = select(AuditRunModel).where(AuditRunModel.archive_id == archive_id)
        if mode is not None:
            statement = statement.where(AuditRunModel.mode == mode.value)
        model = self.session.scalar(
            statement.order_by(AuditRunModel.started_at.desc(), AuditRunModel.id.desc()).limit(1)
        )
        return _audit(model) if model else None

    def find_interrupted(self, archive_id: int | None = None) -> list[AuditRun]:
        statuses = [
            AuditStatus.RUNNING.value,
            AuditStatus.INTERRUPTED.value,
            AuditStatus.PAUSED.value,
        ]
        statement = select(AuditRunModel).where(AuditRunModel.status.in_(statuses))
        if archive_id is not None:
            statement = statement.where(AuditRunModel.archive_id == archive_id)
        models = self.session.scalars(statement.order_by(AuditRunModel.started_at.desc()))
        return [_audit(model) for model in models]

    def list_for_archive(self, archive_id: int) -> list[AuditRun]:
        models = self.session.scalars(
            select(AuditRunModel)
            .where(AuditRunModel.archive_id == archive_id)
            .order_by(AuditRunModel.started_at.desc(), AuditRunModel.id.desc())
        )
        return [_audit(model) for model in models]


class FileRecordRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_batch(self, archive_id: int, records: list[FileRecord]) -> list[int]:
        if not records:
            return []
        values = [
            {
                "archive_id": archive_id,
                "relative_path": record.relative_path,
                "normalized_path": record.normalized_path,
                "size": record.size,
                "mtime_ns": record.mtime_ns,
                "filesystem_identity": record.filesystem_identity,
                "first_seen_audit_id": record.first_seen_audit_id,
                "last_seen_audit_id": record.last_seen_audit_id,
                "present": record.present,
                "last_health": record.last_health.value if record.last_health else None,
                "last_deep_verified_at": record.last_deep_verified_at,
                "last_sha256": record.last_sha256,
            }
            for record in records
        ]
        statement = insert(FileRecordModel).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[FileRecordModel.archive_id, FileRecordModel.normalized_path],
            set_={
                "relative_path": statement.excluded.relative_path,
                "size": statement.excluded.size,
                "mtime_ns": statement.excluded.mtime_ns,
                "filesystem_identity": statement.excluded.filesystem_identity,
                "last_seen_audit_id": statement.excluded.last_seen_audit_id,
                "present": statement.excluded.present,
            },
        )
        self.session.execute(statement)
        paths = {record.normalized_path for record in records}
        rows = self.session.execute(
            select(FileRecordModel.normalized_path, FileRecordModel.id).where(
                FileRecordModel.archive_id == archive_id,
                FileRecordModel.normalized_path.in_(paths),
            )
        )
        ids: dict[str, int] = {path: record_id for path, record_id in rows}
        return [ids[record.normalized_path] for record in records]

    def get_by_normalized_path(self, archive_id: int, normalized_path: str) -> FileRecord | None:
        model = self.session.scalar(
            select(FileRecordModel).where(
                FileRecordModel.archive_id == archive_id,
                FileRecordModel.normalized_path == normalized_path,
            )
        )
        return _file_record(model) if model else None

    def iter_pending_for_run(
        self, archive_id: int, run_id: int, batch_size: int
    ) -> Iterator[FileRecord]:
        has_observation = exists().where(
            ObservationModel.file_record_id == FileRecordModel.id,
            ObservationModel.audit_run_id == run_id,
        )
        models = self.session.scalars(
            select(FileRecordModel)
            .where(
                FileRecordModel.archive_id == archive_id,
                FileRecordModel.last_seen_audit_id == run_id,
                ~has_observation,
            )
            .order_by(FileRecordModel.normalized_path)
            .execution_options(yield_per=batch_size)
        )
        for model in models:
            yield _file_record(model)

    def count_pending_for_run(self, archive_id: int, run_id: int) -> int:
        has_observation = exists().where(
            ObservationModel.file_record_id == FileRecordModel.id,
            ObservationModel.audit_run_id == run_id,
        )
        return int(
            self.session.scalar(
                select(func.count(FileRecordModel.id)).where(
                    FileRecordModel.archive_id == archive_id,
                    FileRecordModel.last_seen_audit_id == run_id,
                    ~has_observation,
                )
            )
            or 0
        )

    def mark_missing_not_seen(self, archive_id: int, run_id: int) -> list[FileRecord]:
        models = list(
            self.session.scalars(
                select(FileRecordModel).where(
                    FileRecordModel.archive_id == archive_id,
                    FileRecordModel.present,
                    FileRecordModel.last_seen_audit_id != run_id,
                )
            )
        )
        for model in models:
            model.present = False
        self.session.flush()
        return [_file_record(model) for model in models]

    def find_by_sha256_and_size(self, archive_id: int, sha256: str, size: int) -> list[FileRecord]:
        models = self.session.scalars(
            select(FileRecordModel)
            .where(
                FileRecordModel.archive_id == archive_id,
                FileRecordModel.last_sha256 == sha256,
                FileRecordModel.size == size,
            )
            .order_by(FileRecordModel.normalized_path)
        )
        return [_file_record(model) for model in models]

    def health_counts(self, archive_id: int) -> dict[HealthState, int]:
        rows = self.session.execute(
            select(FileRecordModel.last_health, func.count(FileRecordModel.id))
            .where(
                FileRecordModel.archive_id == archive_id,
                FileRecordModel.present,
                FileRecordModel.last_health.is_not(None),
            )
            .group_by(FileRecordModel.last_health)
        )
        return {HealthState(health): int(count) for health, count in rows}

    def totals(self, archive_id: int) -> tuple[int, int]:
        count, size = self.session.execute(
            select(
                func.count(FileRecordModel.id), func.coalesce(func.sum(FileRecordModel.size), 0)
            ).where(FileRecordModel.archive_id == archive_id, FileRecordModel.present)
        ).one()
        return int(count), int(size)

    def deep_verification_coverage(self, archive_id: int, within_days: int) -> tuple[int, int]:
        cutoff = utcnow() - timedelta(days=within_days)
        verified, total = self.session.execute(
            select(
                func.count(case((FileRecordModel.last_deep_verified_at >= cutoff, 1))),
                func.count(FileRecordModel.id),
            ).where(FileRecordModel.archive_id == archive_id, FileRecordModel.present)
        ).one()
        return int(verified), int(total)

    def list_present(
        self,
        archive_id: int,
        offset: int = 0,
        limit: int = 100,
        *,
        health: HealthState | None = None,
        path_contains: str | None = None,
    ) -> list[FileRecord]:
        statement = select(FileRecordModel).where(
            FileRecordModel.archive_id == archive_id, FileRecordModel.present
        )
        if health is not None:
            statement = statement.where(FileRecordModel.last_health == health.value)
        if path_contains:
            statement = statement.where(
                FileRecordModel.normalized_path.contains(path_contains.casefold())
            )
        models = self.session.scalars(
            statement.order_by(FileRecordModel.normalized_path).offset(offset).limit(limit)
        )
        return [_file_record(model) for model in models]

    def search(
        self, archive_id: int, query: str, offset: int = 0, limit: int = 100
    ) -> list[FileRecord]:
        pattern = f"%{query.casefold()}%"
        models = self.session.scalars(
            select(FileRecordModel)
            .where(
                FileRecordModel.archive_id == archive_id,
                FileRecordModel.present,
                or_(
                    FileRecordModel.normalized_path.like(pattern),
                    FileRecordModel.relative_path.like(pattern),
                ),
            )
            .order_by(FileRecordModel.normalized_path)
            .offset(offset)
            .limit(limit)
        )
        return [_file_record(model) for model in models]


class ObservationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_batch(self, observations: list[Observation]) -> list[Observation]:
        models = [
            ObservationModel(
                file_record_id=item.file_record_id,
                audit_run_id=item.audit_run_id,
                observed_size=item.observed_size,
                observed_mtime_ns=item.observed_mtime_ns,
                sha256=item.sha256,
                hashed_at=item.hashed_at,
                extension=item.extension,
                detected_format=item.detected_format,
                format_version=item.format_version,
                puid=item.puid,
                mime_type=item.mime_type,
                extension_matches_signature=item.extension_matches_signature,
                identification_warning=item.identification_warning,
                structural_status=item.structural_status.value,
                readability_status=item.readability_status.value,
                policy_status=item.policy_status.value,
                policy_reason=item.policy_reason,
                health=item.health.value,
                change_kind=item.change_kind.value,
                validator_name=item.validator_name,
                validator_version=item.validator_version,
                support_tier=item.support_tier.value,
                validation_details=item.validation_details,
                created_at=item.created_at,
            )
            for item in observations
        ]
        self.session.add_all(models)
        self.session.flush()
        return [_observation(model) for model in models]

    def latest_for_file(self, file_record_id: int) -> Observation | None:
        model = self.session.scalar(
            select(ObservationModel)
            .where(ObservationModel.file_record_id == file_record_id)
            .order_by(ObservationModel.created_at.desc(), ObservationModel.id.desc())
            .limit(1)
        )
        return _observation(model) if model else None

    def history_for_file(self, file_record_id: int) -> list[Observation]:
        models = self.session.scalars(
            select(ObservationModel)
            .where(ObservationModel.file_record_id == file_record_id)
            .order_by(ObservationModel.created_at.desc(), ObservationModel.id.desc())
        )
        return [_observation(model) for model in models]

    def count_for_run(self, run_id: int) -> int:
        return int(
            self.session.scalar(
                select(func.count(ObservationModel.id)).where(
                    ObservationModel.audit_run_id == run_id
                )
            )
            or 0
        )


class FindingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_batch(self, findings: list[Finding]) -> list[Finding]:
        models = [
            FindingModel(
                file_record_id=item.file_record_id,
                audit_run_id=item.audit_run_id,
                code=item.code,
                severity=item.severity.value,
                category=item.category.value,
                title=item.title,
                description=item.description,
                evidence=item.evidence,
                state=item.state.value,
                created_at=item.created_at,
                resolved_at=item.resolved_at,
            )
            for item in findings
        ]
        self.session.add_all(models)
        self.session.flush()
        return [_finding(model) for model in models]

    def list(
        self,
        *,
        archive_id: int | None = None,
        run_id: int | None = None,
        severity: FindingSeverity | None = None,
        category: FindingCategory | None = None,
        state: FindingState | None = None,
        file_record_id: int | None = None,
    ) -> list[Finding]:
        statement = select(FindingModel)
        if archive_id is not None:
            statement = statement.join(AuditRunModel).where(AuditRunModel.archive_id == archive_id)
        if run_id is not None:
            statement = statement.where(FindingModel.audit_run_id == run_id)
        if severity is not None:
            statement = statement.where(FindingModel.severity == severity.value)
        if category is not None:
            statement = statement.where(FindingModel.category == category.value)
        if state is not None:
            statement = statement.where(FindingModel.state == state.value)
        if file_record_id is not None:
            statement = statement.where(FindingModel.file_record_id == file_record_id)
        severity_order = case(
            (FindingModel.severity == FindingSeverity.HIGH.value, 4),
            (FindingModel.severity == FindingSeverity.MEDIUM.value, 3),
            (FindingModel.severity == FindingSeverity.LOW.value, 2),
            else_=1,
        )
        models = self.session.scalars(
            statement.order_by(severity_order.desc(), FindingModel.created_at.desc())
        )
        return [_finding(model) for model in models]

    def update_state(
        self, finding_id: int, state: FindingState, resolved_at: datetime | None = None
    ) -> Finding | None:
        model = self.session.get(FindingModel, finding_id)
        if model is None:
            return None
        model.state = state.value
        model.resolved_at = resolved_at
        self.session.flush()
        return _finding(model)

    def counts_by_severity(self, archive_id: int) -> dict[FindingSeverity, int]:
        rows = self.session.execute(
            select(FindingModel.severity, func.count(FindingModel.id))
            .join(AuditRunModel)
            .where(AuditRunModel.archive_id == archive_id)
            .group_by(FindingModel.severity)
        )
        return {FindingSeverity(severity): int(count) for severity, count in rows}

    def open_for_file(self, file_record_id: int) -> builtins.list[Finding]:
        return self.list(file_record_id=file_record_id, state=FindingState.OPEN)


class GeneratedCopyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, generated_copy: GeneratedCopy) -> GeneratedCopy:
        model = GeneratedCopyModel(
            source_file_record_id=generated_copy.source_file_record_id,
            output_path=generated_copy.output_path,
            copy_kind=generated_copy.copy_kind.value,
            operation=generated_copy.operation,
            created_at=generated_copy.created_at,
            source_hash=generated_copy.source_hash,
            output_hash=generated_copy.output_hash,
            source_analysis=generated_copy.source_analysis,
            output_analysis=generated_copy.output_analysis,
            verification_status=generated_copy.verification_status.value,
            verification_details=generated_copy.verification_details,
            tool_versions=generated_copy.tool_versions,
        )
        self.session.add(model)
        self.session.flush()
        return _generated_copy(model)

    def list_for_file(self, file_record_id: int) -> list[GeneratedCopy]:
        models = self.session.scalars(
            select(GeneratedCopyModel)
            .where(GeneratedCopyModel.source_file_record_id == file_record_id)
            .order_by(GeneratedCopyModel.created_at.desc(), GeneratedCopyModel.id.desc())
        )
        return [_generated_copy(model) for model in models]

    def get(self, generated_copy_id: int) -> GeneratedCopy | None:
        model = self.session.get(GeneratedCopyModel, generated_copy_id)
        return _generated_copy(model) if model else None
