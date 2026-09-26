from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from keepreadable.domain.enums import FindingCategory, FindingSeverity, FindingState


@dataclass(frozen=True, slots=True, kw_only=True)
class Finding:
    id: int | None = None
    file_record_id: int | None
    audit_run_id: int
    code: str
    severity: FindingSeverity
    category: FindingCategory
    title: str
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)
    state: FindingState = FindingState.OPEN
    created_at: datetime
    resolved_at: datetime | None
