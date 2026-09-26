from keepreadable.domain.enums import CheckStatus, HealthState, PolicyStatus


def classify_health(
    *,
    identified: bool,
    extension_matches: bool | None,
    structural: CheckStatus,
    readability: CheckStatus,
    policy: PolicyStatus,
) -> HealthState:
    statuses = {structural, readability}
    if CheckStatus.FAILED in statuses:
        return HealthState.UNREADABLE
    if not identified:
        return HealthState.UNKNOWN
    if (
        statuses & {CheckStatus.PROTECTED, CheckStatus.WARNING, CheckStatus.UNAVAILABLE}
        or policy is PolicyStatus.REVIEW
        or extension_matches is False
    ):
        return HealthState.REVIEW
    return HealthState.HEALTHY
