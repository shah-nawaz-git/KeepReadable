import pytest

from keepreadable.domain.enums import CheckStatus, FindingState
from keepreadable.ui.formatting import label_for, pluralize

pytestmark = pytest.mark.ui


def test_pluralize_and_enum_labels() -> None:
    assert pluralize(1, "file") == "1 file"
    assert pluralize(2, "file") == "2 files"
    assert pluralize(2, "copy", "copies") == "2 copies"
    assert label_for(CheckStatus.NOT_CHECKED) == "Not checked"
    assert label_for(CheckStatus.PASSED) == "Passed"
    assert label_for(FindingState.ACKNOWLEDGED) == "Acknowledged"
