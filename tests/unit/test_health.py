import pytest

from keepreadable.domain.enums import CheckStatus, HealthState, PolicyStatus
from keepreadable.domain.health import classify_health


@pytest.mark.parametrize("failed_field", ["structural", "readability"])
def test_failed_check_is_unreadable(failed_field: str) -> None:
    values = {
        "structural": CheckStatus.PASSED,
        "readability": CheckStatus.PASSED,
    }
    values[failed_field] = CheckStatus.FAILED
    assert (
        classify_health(
            identified=True,
            extension_matches=True,
            structural=values["structural"],
            readability=values["readability"],
            policy=PolicyStatus.NORMAL,
        )
        is HealthState.UNREADABLE
    )


def test_unidentified_is_unknown() -> None:
    assert (
        classify_health(
            identified=False,
            extension_matches=True,
            structural=CheckStatus.PASSED,
            readability=CheckStatus.PASSED,
            policy=PolicyStatus.NORMAL,
        )
        is HealthState.UNKNOWN
    )


@pytest.mark.parametrize(
    ("structural", "readability"),
    [
        (CheckStatus.PROTECTED, CheckStatus.PASSED),
        (CheckStatus.WARNING, CheckStatus.PASSED),
        (CheckStatus.UNAVAILABLE, CheckStatus.PASSED),
        (CheckStatus.PASSED, CheckStatus.PROTECTED),
        (CheckStatus.PASSED, CheckStatus.WARNING),
        (CheckStatus.PASSED, CheckStatus.UNAVAILABLE),
    ],
)
def test_nonpassing_check_is_review(structural: CheckStatus, readability: CheckStatus) -> None:
    assert (
        classify_health(
            identified=True,
            extension_matches=True,
            structural=structural,
            readability=readability,
            policy=PolicyStatus.NORMAL,
        )
        is HealthState.REVIEW
    )


def test_policy_review_is_review() -> None:
    assert (
        classify_health(
            identified=True,
            extension_matches=True,
            structural=CheckStatus.PASSED,
            readability=CheckStatus.PASSED,
            policy=PolicyStatus.REVIEW,
        )
        is HealthState.REVIEW
    )


def test_extension_mismatch_is_review() -> None:
    assert (
        classify_health(
            identified=True,
            extension_matches=False,
            structural=CheckStatus.PASSED,
            readability=CheckStatus.PASSED,
            policy=PolicyStatus.NORMAL,
        )
        is HealthState.REVIEW
    )


@pytest.mark.parametrize("extension_matches", [True, None])
def test_passing_checks_are_healthy(extension_matches: bool | None) -> None:
    assert (
        classify_health(
            identified=True,
            extension_matches=extension_matches,
            structural=CheckStatus.PASSED,
            readability=CheckStatus.NOT_CHECKED,
            policy=PolicyStatus.UNKNOWN,
        )
        is HealthState.HEALTHY
    )
