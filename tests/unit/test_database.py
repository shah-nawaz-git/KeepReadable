from datetime import UTC, datetime

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from keepreadable.persistence.database import Database, SchemaError
from keepreadable.persistence.models import (
    ArchiveModel,
    AuditRunModel,
    ObservationModel,
    SchemaMetaModel,
)


def test_initialization_creates_tables_and_schema_version(db: Database) -> None:
    tables = set(inspect(db.engine).get_table_names())
    assert {
        "archives",
        "audit_runs",
        "file_records",
        "observations",
        "findings",
        "generated_copies",
        "schema_meta",
    } <= tables
    with db.session() as session:
        version = session.get(SchemaMetaModel, "schema_version")
        assert version is not None
        assert version.value == "1"


def test_foreign_keys_are_enforced(db: Database) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    with pytest.raises(IntegrityError), db.session() as session:
        archive = ArchiveModel(
            name="Archive",
            root_path="C:/archive",
            root_fingerprint="fingerprint",
            volume_serial=None,
            volume_label=None,
            created_at=now,
            last_seen_at=None,
            active=True,
        )
        session.add(archive)
        session.flush()
        run = AuditRunModel(
            archive_id=archive.id,
            mode="quick",
            status="running",
            started_at=now,
            completed_at=None,
            policy_version="1",
            signature_version=None,
            tool_versions={},
            files_discovered=0,
            files_processed=0,
            files_failed=0,
            files_skipped=0,
            findings_count=0,
            error_summary=None,
            resume_state={},
            force_deep_all=False,
            interruption_reason=None,
        )
        session.add(run)
        session.flush()
        session.add(
            ObservationModel(
                file_record_id=999,
                audit_run_id=run.id,
                observed_size=1,
                observed_mtime_ns=1,
                sha256=None,
                hashed_at=None,
                extension=".txt",
                detected_format=None,
                format_version=None,
                puid=None,
                mime_type=None,
                extension_matches_signature=None,
                identification_warning=None,
                structural_status="not_checked",
                readability_status="not_checked",
                policy_status="unknown",
                policy_reason=None,
                health="unknown",
                change_kind="new",
                validator_name=None,
                validator_version=None,
                support_tier="identify_only",
                validation_details={},
                created_at=now,
            )
        )


def test_file_database_uses_wal(db: Database) -> None:
    with db.engine.connect() as connection:
        mode = connection.scalar(text("PRAGMA journal_mode"))
    assert mode == "wal"


def test_newer_schema_version_is_rejected(db: Database) -> None:
    with db.session() as session:
        meta = session.get(SchemaMetaModel, "schema_version")
        assert meta is not None
        meta.value = "2"
    with pytest.raises(SchemaError, match="newer than supported"):
        db.initialize()


def test_session_rolls_back_on_exception(db: Database) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    with pytest.raises(RuntimeError, match="stop"), db.session() as session:
        session.add(
            ArchiveModel(
                name="Archive",
                root_path="C:/archive",
                root_fingerprint="fingerprint",
                volume_serial=None,
                volume_label=None,
                created_at=now,
                last_seen_at=None,
                active=True,
            )
        )
        session.flush()
        raise RuntimeError("stop")
    with db.session() as session:
        assert session.scalar(select(func.count(ArchiveModel.id))) == 0
