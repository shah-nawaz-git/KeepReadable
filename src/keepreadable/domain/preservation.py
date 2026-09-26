from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum, auto
from typing import Any

from keepreadable.domain.enums import CopyKind, VerificationStatus


class CopyOperation(StrEnum):
    VIDEO_TO_MP4 = auto()
    BMP_TO_PNG = auto()


@dataclass(frozen=True, slots=True, kw_only=True)
class GeneratedCopy:
    id: int | None = None
    source_file_record_id: int
    output_path: str | None
    copy_kind: CopyKind
    operation: str
    created_at: datetime
    source_hash: str
    output_hash: str | None
    source_analysis: dict[str, Any] = field(default_factory=dict)
    output_analysis: dict[str, Any] = field(default_factory=dict)
    verification_status: VerificationStatus
    verification_details: dict[str, Any] = field(default_factory=dict)
    tool_versions: dict[str, str] = field(default_factory=dict)
