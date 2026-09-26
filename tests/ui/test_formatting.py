import pytest

from keepreadable.domain.enums import (
    CheckStatus,
    FindingSeverity,
    FindingState,
    HealthState,
)
from keepreadable.ui.formatting import label_for, pluralize
from keepreadable.ui.theme import palette

pytestmark = pytest.mark.ui


def test_pluralize_and_enum_labels() -> None:
    assert pluralize(1, "file") == "1 file"
    assert pluralize(2, "file") == "2 files"
    assert pluralize(2, "copy", "copies") == "2 copies"
    assert label_for(CheckStatus.NOT_CHECKED) == "Not checked"
    assert label_for(CheckStatus.PASSED) == "Passed"
    assert label_for(FindingState.ACKNOWLEDGED) == "Acknowledged"


def test_central_health_and_severity_colours() -> None:
    assert palette.severity_colour(FindingSeverity.INFO) == "#4A5568"
    assert palette.severity_colour(FindingSeverity.LOW) == palette.UNKNOWN
    assert palette.severity_colour(FindingSeverity.MEDIUM) == palette.REVIEW
    assert palette.severity_colour(FindingSeverity.HIGH) == palette.UNREADABLE
    assert palette.health_colour(HealthState.HEALTHY) == palette.HEALTHY
    assert palette.health_colour(HealthState.REVIEW) == palette.REVIEW
    assert palette.health_colour(HealthState.UNREADABLE) == palette.UNREADABLE
    assert palette.health_colour(HealthState.UNKNOWN) == palette.UNKNOWN
