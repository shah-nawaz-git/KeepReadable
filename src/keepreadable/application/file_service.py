from dataclasses import dataclass
from pathlib import Path

from keepreadable.domain.enums import FindingState, HealthState
from keepreadable.domain.file_record import FileRecord
from keepreadable.domain.finding import Finding
from keepreadable.domain.observation import Observation
from keepreadable.domain.preservation import GeneratedCopy
from keepreadable.persistence.database import Database
from keepreadable.persistence.repositories import (
    ArchiveRepository,
    FileRecordRepository,
    FindingRepository,
    GeneratedCopyRepository,
    ObservationRepository,
)
from keepreadable.utilities.clock import utcnow


@dataclass(frozen=True, slots=True)
class FileDetail:
    record: FileRecord
    latest_observation: Observation | None
    history: list[Observation]
    open_findings: list[Finding]
    generated_copies: list[GeneratedCopy]
    absolute_path: Path


class FileService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list_files(
        self,
        archive_id: int,
        offset: int,
        limit: int,
        health: HealthState | None = None,
        search: str | None = None,
    ) -> list[FileRecord]:
        with self.db.session() as session:
            repository = FileRecordRepository(session)
            if search:
                return repository.search(archive_id, search, offset, limit)
            return repository.list_present(archive_id, offset, limit, health=health)

    def file_detail(self, file_record_id: int) -> FileDetail:
        with self.db.session() as session:
            files = FileRecordRepository(session)
            record = files.get(file_record_id)
            if record is None:
                raise ValueError(f"File record {file_record_id} does not exist")
            archive = ArchiveRepository(session).get(record.archive_id)
            if archive is None:
                raise ValueError(f"Archive {record.archive_id} does not exist")
            observations = ObservationRepository(session)
            return FileDetail(
                record,
                observations.latest_for_file(file_record_id),
                observations.history_for_file(file_record_id),
                FindingRepository(session).open_for_file(file_record_id),
                GeneratedCopyRepository(session).list_for_file(file_record_id),
                Path(archive.root_path) / record.relative_path,
            )

    def set_finding_state(self, finding_id: int, state: FindingState) -> Finding | None:
        resolved_at = utcnow() if state is FindingState.RESOLVED else None
        with self.db.session() as session:
            return FindingRepository(session).update_state(finding_id, state, resolved_at)
