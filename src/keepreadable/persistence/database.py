from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from sqlalchemy import Connection, Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from keepreadable.persistence.models import Base, SchemaMetaModel

SCHEMA_VERSION = 1


class SchemaError(RuntimeError):
    pass


class Database:
    def __init__(self, path: Path | Literal[":memory:"]) -> None:
        self.path = path
        memory = path == ":memory:"
        if not memory:
            assert isinstance(path, Path)
            path.parent.mkdir(parents=True, exist_ok=True)
        url = "sqlite+pysqlite:///:memory:" if memory else f"sqlite+pysqlite:///{path}"
        self.engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        self._configure_sqlite(self.engine, memory)
        self._session_factory = sessionmaker(self.engine, expire_on_commit=False)

    @staticmethod
    def _configure_sqlite(engine: Engine, memory: bool) -> None:
        @event.listens_for(engine, "connect")
        def set_pragmas(dbapi_connection: object, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            if not memory:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            columns = {
                str(row[1]) for row in connection.exec_driver_sql("PRAGMA table_info(file_records)")
            }
            if "last_format" not in columns:
                connection.exec_driver_sql(
                    "ALTER TABLE file_records ADD COLUMN last_format VARCHAR(255)"
                )
            copy_columns = list(connection.exec_driver_sql("PRAGMA table_info(generated_copies)"))
            output_column = next((row for row in copy_columns if row[1] == "output_path"), None)
            if output_column is not None and int(output_column[3]) == 1:
                self._make_copy_output_nullable(connection)
        with self.session() as session:
            meta = session.scalar(
                select(SchemaMetaModel).where(SchemaMetaModel.key == "schema_version")
            )
            if meta is None:
                session.add(SchemaMetaModel(key="schema_version", value=str(SCHEMA_VERSION)))
                return
            version = int(meta.value)
            if version > SCHEMA_VERSION:
                raise SchemaError(
                    f"Database schema version {version} is newer than supported version "
                    f"{SCHEMA_VERSION}"
                )

    @staticmethod
    def _make_copy_output_nullable(connection: Connection) -> None:
        connection.exec_driver_sql(
            "ALTER TABLE generated_copies RENAME TO generated_copies_required_output"
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE generated_copies (
                id INTEGER NOT NULL PRIMARY KEY,
                source_file_record_id INTEGER NOT NULL
                    REFERENCES file_records(id) ON DELETE CASCADE,
                output_path TEXT,
                copy_kind VARCHAR(64) NOT NULL,
                operation VARCHAR(255) NOT NULL,
                created_at DATETIME NOT NULL,
                source_hash VARCHAR(64) NOT NULL,
                output_hash VARCHAR(64),
                source_analysis JSON NOT NULL,
                output_analysis JSON NOT NULL,
                verification_status VARCHAR(32) NOT NULL,
                verification_details JSON NOT NULL,
                tool_versions JSON NOT NULL
            )
            """
        )
        columns = (
            "id, source_file_record_id, output_path, copy_kind, operation, created_at, "
            "source_hash, output_hash, source_analysis, output_analysis, verification_status, "
            "verification_details, tool_versions"
        )
        connection.exec_driver_sql(
            f"INSERT INTO generated_copies ({columns}) "
            f"SELECT {columns} FROM generated_copies_required_output"
        )
        connection.exec_driver_sql("DROP TABLE generated_copies_required_output")

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
