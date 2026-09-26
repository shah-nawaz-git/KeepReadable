import time
from dataclasses import dataclass
from pathlib import Path

from keepreadable.analysis.archive_identity import (
    ArchiveAvailability,
    compute_root_fingerprint,
    get_volume_info,
    resolve_archive_root,
)
from keepreadable.analysis.discovery import DiscoveryOptions, discover_files
from keepreadable.config.paths import data_dir
from keepreadable.config.settings import Settings
from keepreadable.domain.archive import Archive
from keepreadable.domain.audit import AuditRun
from keepreadable.domain.enums import AuditMode, FindingSeverity, HealthState
from keepreadable.domain.finding import Finding
from keepreadable.persistence.database import Database
from keepreadable.persistence.repositories import (
    ArchiveRepository,
    AuditRunRepository,
    FileRecordRepository,
    FindingRepository,
)
from keepreadable.utilities.clock import utcnow


@dataclass(frozen=True, slots=True)
class ArchiveOverview:
    name: str
    root: str
    availability: ArchiveAvailability
    file_count: int
    total_bytes: int
    health_counts: dict[HealthState, int]
    last_quick_run: AuditRun | None
    last_deep_run: AuditRun | None
    verified_count: int
    verification_total: int
    coverage_percent: float
    interval_days: int
    open_findings_by_severity: dict[FindingSeverity, int]
    top_findings: list[Finding]


class ArchiveService:
    def __init__(self, db: Database, settings: Settings, app_data_dir: Path | None = None) -> None:
        self.db = db
        self.settings = settings
        self.app_data_dir = app_data_dir or data_dir()

    def add_archive(self, name: str, root: Path) -> Archive:
        root = root.resolve()
        if not root.is_dir():
            raise ValueError("Archive root must be an existing directory")
        app_data = self.app_data_dir.resolve()
        if app_data == root or app_data.is_relative_to(root):
            raise ValueError("Archive root must not contain the KeepReadable data directory")
        volume = get_volume_info(root)
        fingerprint = compute_root_fingerprint(root, volume)
        with self.db.session() as session:
            repository = ArchiveRepository(session)
            if repository.find_by_fingerprint(fingerprint) is not None:
                raise ValueError("This archive root is already registered")
            return repository.add(
                Archive(
                    name=name,
                    root_path=str(root),
                    root_fingerprint=fingerprint,
                    volume_serial=volume.serial,
                    volume_label=volume.label,
                    created_at=utcnow(),
                    last_seen_at=None,
                )
            )

    def list_archives(self) -> list[Archive]:
        with self.db.session() as session:
            return ArchiveRepository(session).list_active()

    def remove_archive(self, archive_id: int) -> bool:
        with self.db.session() as session:
            return ArchiveRepository(session).delete(archive_id)

    def overview(self, archive_id: int) -> ArchiveOverview:
        with self.db.session() as session:
            archives = ArchiveRepository(session)
            archive = archives.get(archive_id)
            if archive is None:
                raise ValueError(f"Archive {archive_id} does not exist")
            resolved = resolve_archive_root(archive.root_path, archive.root_fingerprint)
            files = FileRecordRepository(session)
            findings = FindingRepository(session)
            runs = AuditRunRepository(session)
            count, total_bytes = files.totals(archive_id)
            verified, verification_total = files.deep_verification_coverage(
                archive_id, self.settings.deep_verification_interval_days
            )
            current = findings.latest_findings(archive_id)
            counts: dict[FindingSeverity, int] = {}
            for finding in current:
                counts[finding.severity] = counts.get(finding.severity, 0) + 1
            return ArchiveOverview(
                archive.name,
                archive.root_path,
                resolved.availability,
                count,
                total_bytes,
                files.health_counts(archive_id),
                runs.latest_for_archive(archive_id, AuditMode.QUICK),
                runs.latest_for_archive(archive_id, AuditMode.DEEP),
                verified,
                verification_total,
                (verified / verification_total * 100) if verification_total else 0.0,
                self.settings.deep_verification_interval_days,
                counts,
                current[:10],
            )

    def history(self, archive_id: int) -> list[AuditRun]:
        with self.db.session() as session:
            return AuditRunRepository(session).list_for_archive(archive_id)

    def estimate_file_count(self, root: Path, limit: int = 5000, time_budget: float = 2.0) -> int:
        started = time.monotonic()
        count = 0
        for _item in discover_files(
            root,
            DiscoveryOptions(self.settings.follow_reparse_points),
        ):
            count += 1
            if count >= limit or time.monotonic() - started >= time_budget:
                break
        return count
