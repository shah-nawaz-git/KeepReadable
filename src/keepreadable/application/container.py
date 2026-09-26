from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from keepreadable.application.archive_service import ArchiveService
from keepreadable.application.audit_service import AuditEngine
from keepreadable.application.file_service import FileService
from keepreadable.application.findings_service import FindingsService
from keepreadable.application.preservation_service import PreservationService
from keepreadable.application.report_service import ReportService
from keepreadable.config.paths import data_dir as default_data_dir
from keepreadable.config.settings import Settings, load_settings
from keepreadable.integrations.ffmpeg import FFmpegAdapter
from keepreadable.integrations.siegfried import SiegfriedAdapter
from keepreadable.integrations.tool_locator import ToolLocator, ToolName
from keepreadable.persistence.database import Database
from keepreadable.policies.registry import PolicyRegistry
from keepreadable.validators.registry import ValidatorRegistry


@dataclass(frozen=True, slots=True)
class AppContext:
    settings: Settings
    db: Database
    tool_locator: ToolLocator
    siegfried: SiegfriedAdapter | None
    ffmpeg: FFmpegAdapter | None
    validators: ValidatorRegistry
    policy: PolicyRegistry
    archive_service: ArchiveService
    audit_engine: AuditEngine
    file_service: FileService
    findings_service: FindingsService
    preservation_service: PreservationService
    report_service: ReportService

    @classmethod
    def create(
        cls,
        data_dir: Path | None = None,
        settings: Settings | None = None,
        tool_locator: ToolLocator | None = None,
    ) -> AppContext:
        root = data_dir or default_data_dir()
        root.mkdir(parents=True, exist_ok=True)
        configured = settings or load_settings(root / "settings.json")
        database = Database(root / "keepreadable.db")
        database.initialize()
        locator = tool_locator or ToolLocator(tools_dir=root / "tools")
        sf_path = locator.locate(ToolName.SIEGFRIED)
        sf_home = locator.siegfried_home()
        siegfried = (
            SiegfriedAdapter(
                sf_path,
                sf_home,
                timeout=configured.subprocess_timeout_seconds,
                multi=max(1, configured.worker_count),
            )
            if sf_path is not None and sf_home is not None
            else None
        )
        ffmpeg_path = locator.locate(ToolName.FFMPEG)
        ffprobe_path = locator.locate(ToolName.FFPROBE)
        ffmpeg = (
            FFmpegAdapter(
                ffmpeg_path,
                ffprobe_path,
                timeout=configured.subprocess_timeout_seconds,
            )
            if ffmpeg_path is not None and ffprobe_path is not None
            else None
        )
        validators = ValidatorRegistry(ffmpeg=ffmpeg)
        policy = PolicyRegistry.load_default()
        archives = ArchiveService(database, configured, root)
        files = FileService(database)
        findings = FindingsService(database)
        report_service = ReportService(database, configured, validators)
        preservation = PreservationService(
            database,
            configured,
            ffmpeg=ffmpeg,
            validators=validators,
        )
        engine = AuditEngine(
            database,
            configured,
            siegfried=siegfried,
            ffmpeg=ffmpeg,
            validators=validators,
            policy=policy,
        )
        return cls(
            configured,
            database,
            locator,
            siegfried,
            ffmpeg,
            validators,
            policy,
            archives,
            engine,
            files,
            findings,
            preservation,
            report_service,
        )
