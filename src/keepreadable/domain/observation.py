from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from keepreadable.domain.enums import (
    ChangeKind,
    CheckStatus,
    HealthState,
    PolicyStatus,
    SupportTier,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Observation:
    id: int | None = None
    file_record_id: int
    audit_run_id: int
    observed_size: int
    observed_mtime_ns: int
    sha256: str | None
    hashed_at: datetime | None
    extension: str
    detected_format: str | None
    format_version: str | None
    puid: str | None
    mime_type: str | None
    extension_matches_signature: bool | None
    identification_warning: str | None
    structural_status: CheckStatus
    readability_status: CheckStatus
    policy_status: PolicyStatus
    policy_reason: str | None
    health: HealthState
    change_kind: ChangeKind
    validator_name: str | None
    validator_version: str | None
    support_tier: SupportTier
    validation_details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime
