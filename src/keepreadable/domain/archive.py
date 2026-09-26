from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class Archive:
    id: int | None = None
    name: str
    root_path: str
    root_fingerprint: str
    volume_serial: str | None
    volume_label: str | None
    created_at: datetime
    last_seen_at: datetime | None
    active: bool = True
