from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pytest

from keepreadable.domain.enums import CheckStatus
from keepreadable.validators.base import EvidenceCode, ValidationDepth, ValidationResult
from keepreadable.validators.ooxml import OoxmlValidator
from tests.fixture_factory import (
    corrupt_zip_member_xml,
    make_docx,
    make_fake_ole,
    make_pptx,
    make_xlsx,
    remove_zip_member,
)


@pytest.mark.parametrize(
    ("kind", "factory", "detail", "expected"),
    [
        ("docx", make_docx, "paragraph_count", 2),
        ("xlsx", make_xlsx, "sheet_count", 2),
        ("pptx", make_pptx, "slide_count", 1),
    ],
)
def test_healthy_ooxml_deep_load(
    tmp_path: Path,
    kind: Literal["docx", "xlsx", "pptx"],
    factory: Callable[[Path], Path],
    detail: str,
    expected: int,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    result = record_validation(
        OoxmlValidator(kind).validate(
            factory(tmp_path / f"file.{kind}"), depth=ValidationDepth.DEEP
        )
    )
    assert result.structural is CheckStatus.PASSED
    assert result.readability is CheckStatus.PASSED
    assert result.details[detail] == expected
    assert "visual rendering / layout fidelity" in result.checks_not_performed


def test_not_zip_and_missing_parts_fail(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    plain = tmp_path / "plain.docx"
    plain.write_bytes(b"not a package")
    source = make_docx(tmp_path / "source.docx")
    missing_types = remove_zip_member(
        source, tmp_path / "missing-types.docx", "[Content_Types].xml"
    )
    missing_main = remove_zip_member(source, tmp_path / "missing-main.docx", "word/document.xml")
    for path in (plain, missing_types, missing_main):
        result = record_validation(
            OoxmlValidator("docx").validate(path, depth=ValidationDepth.DEEP)
        )
        assert result.structural is CheckStatus.FAILED


def test_broken_xml_reports_member_name(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    source = make_docx(tmp_path / "source.docx")
    path = corrupt_zip_member_xml(source, tmp_path / "broken.docx", "word/document.xml")
    result = record_validation(OoxmlValidator("docx").validate(path, depth=ValidationDepth.DEEP))
    assert result.structural is CheckStatus.FAILED
    assert result.details["failed_members"] == ["word/document.xml"]


def test_fake_ole_is_protected(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    result = record_validation(
        OoxmlValidator("docx").validate(
            make_fake_ole(tmp_path / "protected.docx"), depth=ValidationDepth.DEEP
        )
    )
    assert result.structural is CheckStatus.NOT_CHECKED
    assert result.readability is CheckStatus.PROTECTED
    assert EvidenceCode.PROTECTED_CONTENT in result.codes


def test_library_failure_is_decode_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    path = make_docx(tmp_path / "document.docx")

    def fail(_path: str) -> None:
        raise RuntimeError("library failure")

    monkeypatch.setattr("keepreadable.validators.ooxml.docx.Document", fail)
    result = record_validation(OoxmlValidator("docx").validate(path, depth=ValidationDepth.DEEP))
    assert result.structural is CheckStatus.PASSED
    assert result.readability is CheckStatus.FAILED
    assert EvidenceCode.DECODE_FAILURE in result.codes
