from dataclasses import dataclass

from keepreadable.domain.enums import FindingCategory, FindingSeverity, FindingState
from keepreadable.domain.finding import Finding
from keepreadable.persistence.database import Database
from keepreadable.persistence.repositories import (
    ArchiveRepository,
    AuditRunRepository,
    FileRecordRepository,
    FindingRepository,
)


@dataclass(frozen=True, slots=True)
class FindingDisplay:
    finding: Finding
    archive_name: str
    relative_path: str | None


class FindingsService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list_findings(
        self,
        archive_id: int | None = None,
        severity: FindingSeverity | None = None,
        category: FindingCategory | None = None,
        state: FindingState | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FindingDisplay]:
        with self.db.session() as session:
            findings = FindingRepository(session).list(
                archive_id=archive_id,
                severity=severity,
                category=category,
                state=state,
            )[offset : offset + limit]
            output: list[FindingDisplay] = []
            for finding in findings:
                run = AuditRunRepository(session).get(finding.audit_run_id)
                archive = ArchiveRepository(session).get(run.archive_id) if run else None
                record = (
                    FileRecordRepository(session).get(finding.file_record_id)
                    if finding.file_record_id is not None
                    else None
                )
                output.append(
                    FindingDisplay(
                        finding,
                        archive.name if archive else "Unknown archive",
                        record.relative_path if record else None,
                    )
                )
            return output
