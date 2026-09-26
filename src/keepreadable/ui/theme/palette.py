from keepreadable.domain.enums import FindingSeverity, HealthState

BACKGROUND = "#F5F7FA"
SURFACE = "#FFFFFF"
BORDER = "#D9DEE5"
TEXT = "#1F2933"
MUTED_TEXT = "#52606D"
ACCENT = "#2F6FED"
ACCENT_HOVER = "#245BD1"
HEALTHY = "#1E8E5A"
REVIEW = "#B7791F"
UNREADABLE = "#C53030"
UNKNOWN = "#6B7280"
INFO = "#4A5568"
LOW = UNKNOWN


def severity_colour(severity: FindingSeverity) -> str:
    return {
        FindingSeverity.INFO: INFO,
        FindingSeverity.LOW: LOW,
        FindingSeverity.MEDIUM: REVIEW,
        FindingSeverity.HIGH: UNREADABLE,
    }[severity]


def health_colour(health: HealthState) -> str:
    return {
        HealthState.HEALTHY: HEALTHY,
        HealthState.REVIEW: REVIEW,
        HealthState.UNREADABLE: UNREADABLE,
        HealthState.UNKNOWN: UNKNOWN,
    }[health]
