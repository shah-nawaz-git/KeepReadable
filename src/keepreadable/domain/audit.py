from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from keepreadable.domain.enums import AuditMode, AuditStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditRun:
    id: int | None = None
    archive_id: int
    mode: AuditMode
    status: AuditStatus
    started_at: datetime
    completed_at: datetime | None
    policy_version: str
    signature_version: str | None
    tool_versions: dict[str, str] = field(default_factory=dict)
    files_discovered: int = 0
    files_processed: int = 0
    files_failed: int = 0
    files_skipped: int = 0
    findings_count: int = 0
    error_summary: str | None = None
    resume_state: dict[str, Any] = field(default_factory=dict)
    force_deep_all: bool = False
    interruption_reason: str | None = None
