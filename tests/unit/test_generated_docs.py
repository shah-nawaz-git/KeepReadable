from pathlib import Path

from scripts.generate_format_support import generate_document


def test_format_support_document_is_current() -> None:
    path = Path(__file__).parents[2] / "docs" / "FORMAT_SUPPORT.md"
    assert path.read_text(encoding="utf-8") == generate_document()
