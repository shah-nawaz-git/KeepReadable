from dataclasses import dataclass
from datetime import datetime

from keepreadable.domain.enums import HealthState


@dataclass(frozen=True, slots=True, kw_only=True)
class FileRecord:
    id: int | None = None
    archive_id: int
    relative_path: str
    normalized_path: str
    size: int
    mtime_ns: int
    filesystem_identity: str | None
    first_seen_audit_id: int
    last_seen_audit_id: int
    present: bool
    last_health: HealthState | None
    last_deep_verified_at: datetime | None
    last_sha256: str | None
    last_format: str | None = None
