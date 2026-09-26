from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ArchiveModel(Base):
    __tablename__ = "archives"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    root_path: Mapped[str] = mapped_column(Text)
    root_fingerprint: Mapped[str] = mapped_column(String(255), index=True)
    volume_serial: Mapped[str | None] = mapped_column(String(255))
    volume_label: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditRunModel(Base):
    __tablename__ = "audit_runs"
    __table_args__ = (Index("ix_audit_runs_archive_status", "archive_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    archive_id: Mapped[int] = mapped_column(ForeignKey("archives.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    policy_version: Mapped[str] = mapped_column(String(255))
    signature_version: Mapped[str | None] = mapped_column(String(255))
    tool_versions: Mapped[dict[str, str]] = mapped_column(JSON)
    files_discovered: Mapped[int] = mapped_column(Integer, default=0)
    files_processed: Mapped[int] = mapped_column(Integer, default=0)
    files_failed: Mapped[int] = mapped_column(Integer, default=0)
    files_skipped: Mapped[int] = mapped_column(Integer, default=0)
    findings_count: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    resume_state: Mapped[dict[str, Any]] = mapped_column(JSON)
    force_deep_all: Mapped[bool] = mapped_column(Boolean, default=False)
    interruption_reason: Mapped[str | None] = mapped_column(Text)


class FileRecordModel(Base):
    __tablename__ = "file_records"
    __table_args__ = (
        Index("uq_file_records_archive_path", "archive_id", "normalized_path", unique=True),
        Index("ix_file_records_archive_present", "archive_id", "present"),
        Index("ix_file_records_archive_sha256", "archive_id", "last_sha256"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    archive_id: Mapped[int] = mapped_column(ForeignKey("archives.id", ondelete="CASCADE"))
    relative_path: Mapped[str] = mapped_column(Text)
    normalized_path: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(BigInteger)
    mtime_ns: Mapped[int] = mapped_column(BigInteger)
    filesystem_identity: Mapped[str | None] = mapped_column(String(255))
    first_seen_audit_id: Mapped[int] = mapped_column(ForeignKey("audit_runs.id"))
    last_seen_audit_id: Mapped[int] = mapped_column(ForeignKey("audit_runs.id"))
    present: Mapped[bool] = mapped_column(Boolean)
    last_health: Mapped[str | None] = mapped_column(String(32))
    last_deep_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_sha256: Mapped[str | None] = mapped_column(String(64))
    last_format: Mapped[str | None] = mapped_column(String(255))


class ObservationModel(Base):
    __tablename__ = "observations"
    __table_args__ = (
        Index("ix_observations_file_created", "file_record_id", "created_at"),
        Index("ix_observations_audit_run", "audit_run_id"),
        Index("ix_observations_run_file", "audit_run_id", "file_record_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    file_record_id: Mapped[int] = mapped_column(ForeignKey("file_records.id", ondelete="CASCADE"))
    audit_run_id: Mapped[int] = mapped_column(ForeignKey("audit_runs.id", ondelete="CASCADE"))
    observed_size: Mapped[int] = mapped_column(BigInteger)
    observed_mtime_ns: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    hashed_at: Mapped[datetime | None] = mapped_column(DateTime)
    extension: Mapped[str] = mapped_column(String(255))
    detected_format: Mapped[str | None] = mapped_column(String(255))
    format_version: Mapped[str | None] = mapped_column(String(255))
    puid: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(255))
    extension_matches_signature: Mapped[bool | None] = mapped_column(Boolean)
    identification_warning: Mapped[str | None] = mapped_column(Text)
    structural_status: Mapped[str] = mapped_column(String(32))
    readability_status: Mapped[str] = mapped_column(String(32))
    policy_status: Mapped[str] = mapped_column(String(32))
    policy_reason: Mapped[str | None] = mapped_column(Text)
    health: Mapped[str] = mapped_column(String(32))
    change_kind: Mapped[str] = mapped_column(String(32))
    validator_name: Mapped[str | None] = mapped_column(String(255))
    validator_version: Mapped[str | None] = mapped_column(String(255))
    support_tier: Mapped[str] = mapped_column(String(32))
    validation_details: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class FindingModel(Base):
    __tablename__ = "findings"
    __table_args__ = (
        Index("ix_findings_audit_run", "audit_run_id"),
        Index("ix_findings_file_record", "file_record_id"),
        Index("ix_findings_state", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    file_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("file_records.id", ondelete="CASCADE")
    )
    audit_run_id: Mapped[int] = mapped_column(ForeignKey("audit_runs.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


class GeneratedCopyModel(Base):
    __tablename__ = "generated_copies"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_file_record_id: Mapped[int] = mapped_column(
        ForeignKey("file_records.id", ondelete="CASCADE")
    )
    output_path: Mapped[str | None] = mapped_column(Text)
    copy_kind: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    source_hash: Mapped[str] = mapped_column(String(64))
    output_hash: Mapped[str | None] = mapped_column(String(64))
    source_analysis: Mapped[dict[str, Any]] = mapped_column(JSON)
    output_analysis: Mapped[dict[str, Any]] = mapped_column(JSON)
    verification_status: Mapped[str] = mapped_column(String(32))
    verification_details: Mapped[dict[str, Any]] = mapped_column(JSON)
    tool_versions: Mapped[dict[str, str]] = mapped_column(JSON)


class SchemaMetaModel(Base):
    __tablename__ = "schema_meta"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
