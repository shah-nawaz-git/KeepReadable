from keepreadable.analysis.finding_texts import FINDING_TEXTS
from keepreadable.domain.enums import FindingCode


def test_every_finding_code_has_four_safe_paragraphs() -> None:
    forbidden = (
        "corrupt",
        "guaranteed",
        "permanently",
        "future-proof",
        "fully valid",
        "archival master",
        "100%",
    )
    assert set(FINDING_TEXTS) == {code.value for code in FindingCode}
    for text in FINDING_TEXTS.values():
        description = text.description()
        assert len(description.split("\n\n")) == 4
        assert not any(term in description.casefold() for term in forbidden)
        assert not any(term in text.title.casefold() for term in forbidden)
