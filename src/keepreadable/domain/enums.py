from enum import StrEnum, auto


class AuditMode(StrEnum):
    QUICK = auto()
    DEEP = auto()


class AuditStatus(StrEnum):
    PENDING = auto()
    RUNNING = auto()
    PAUSED = auto()
    INTERRUPTED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class HealthState(StrEnum):
    HEALTHY = auto()
    REVIEW = auto()
    UNREADABLE = auto()
    UNKNOWN = auto()


class CheckStatus(StrEnum):
    PASSED = auto()
    WARNING = auto()
    FAILED = auto()
    PROTECTED = auto()
    NOT_CHECKED = auto()
    UNAVAILABLE = auto()


class PolicyStatus(StrEnum):
    NORMAL = auto()
    REVIEW = auto()
    UNKNOWN = auto()


class FindingSeverity(StrEnum):
    INFO = auto()
    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()


class FindingCategory(StrEnum):
    INTEGRITY_CHANGE = auto()
    UNREADABLE = auto()
    STRUCTURAL_WARNING = auto()
    EXTENSION_MISMATCH = auto()
    FORMAT_REVIEW = auto()
    UNKNOWN_FORMAT = auto()
    VALIDATION_UNAVAILABLE = auto()
    SCAN_ERROR = auto()
    PROTECTED = auto()
    DUPLICATE = auto()
    FILE_MISSING = auto()
    POLICY_CHANGE = auto()


class FindingState(StrEnum):
    OPEN = auto()
    ACKNOWLEDGED = auto()
    RESOLVED = auto()
    IGNORED = auto()


class ChangeKind(StrEnum):
    NEW = auto()
    UNCHANGED = auto()
    MODIFIED = auto()
    MISSING = auto()
    MOVED = auto()
    CHANGED_DURING_SCAN = auto()


class CopyKind(StrEnum):
    ACCESS_COPY = auto()
    PRESERVATION_ORIENTED_COPY = auto()


class VerificationStatus(StrEnum):
    PASSED = auto()
    LIMITED = auto()
    FAILED = auto()
    NOT_RUN = auto()


class SupportTier(StrEnum):
    DEEP = auto()
    STRUCTURAL = auto()
    IDENTIFY_ONLY = auto()


class FindingCode(StrEnum):
    INTEGRITY_MISMATCH = auto()
    STRUCTURAL_FAILURE = auto()
    DECODE_FAILURE = auto()
    UNEXPECTED_TRUNCATION = auto()
    VALIDATION_WARNING = auto()
    EXTENSION_MISMATCH = auto()
    UNKNOWN_FORMAT = auto()
    FORMAT_REVIEW = auto()
    VALIDATION_UNAVAILABLE = auto()
    TOOL_UNAVAILABLE = auto()
    SCAN_ERROR = auto()
    PROTECTED_CONTENT = auto()
    FILE_CHANGED_DURING_SCAN = auto()
    FILE_MISSING = auto()
    DUPLICATE_CONTENT = auto()
    POLICY_CLASSIFICATION_CHANGED = auto()
