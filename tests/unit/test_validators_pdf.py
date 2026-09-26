from collections.abc import Callable
from pathlib import Path

import pytest

from keepreadable.domain.enums import CheckStatus
from keepreadable.validators.base import EvidenceCode, ValidationDepth, ValidationResult
from keepreadable.validators.pdf import PdfValidator
from tests.fixture_factory import (
    make_encrypted_pdf,
    make_malformed_pdf,
    make_pdf,
    make_pdf_with_missing_eof,
    make_truncated_pdf,
)


@pytest.mark.parametrize("pages", [1, 3, 20])
def test_healthy_pdf_page_counts(
    tmp_path: Path,
    pages: int,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    result = record_validation(
        PdfValidator().validate(
            make_pdf(tmp_path / f"pages-{pages}.pdf", pages), depth=ValidationDepth.DEEP
        )
    )
    assert result.structural is CheckStatus.PASSED
    assert result.readability is CheckStatus.PASSED
    assert result.details["page_count"] == pages
    assert result.details["pypdf_page_count"] == pages
    assert "PDF/A or ISO conformance validation" in result.checks_not_performed
    assert "conformance was not checked" in result.summary


def test_encrypted_pdf_is_protected(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    result = record_validation(
        PdfValidator().validate(
            make_encrypted_pdf(tmp_path / "encrypted.pdf"), depth=ValidationDepth.DEEP
        )
    )
    assert result.structural is CheckStatus.PASSED
    assert result.readability is CheckStatus.PROTECTED
    assert EvidenceCode.PROTECTED_CONTENT in result.codes


def test_truncated_and_malformed_pdf_fail_structure(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    truncated = record_validation(
        PdfValidator().validate(
            make_truncated_pdf(tmp_path / "truncated.pdf"), depth=ValidationDepth.DEEP
        )
    )
    malformed = record_validation(
        PdfValidator().validate(
            make_malformed_pdf(tmp_path / "malformed.pdf"), depth=ValidationDepth.DEEP
        )
    )
    assert truncated.structural in {CheckStatus.FAILED, CheckStatus.PASSED}
    assert EvidenceCode.UNEXPECTED_TRUNCATION in truncated.codes
    assert malformed.structural is CheckStatus.FAILED


def test_missing_eof_is_warning_not_failure(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    result = record_validation(
        PdfValidator().validate(
            make_pdf_with_missing_eof(tmp_path / "missing-eof.pdf"),
            depth=ValidationDepth.QUICK,
        )
    )
    assert result.structural is CheckStatus.PASSED
    assert EvidenceCode.VALIDATION_WARNING in result.codes
    assert any("end-of-file marker not found" in warning for warning in result.warnings)


def test_garbage_pdf_fails_structure(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    path = tmp_path / "garbage.pdf"
    path.write_bytes(b"not a PDF")
    result = record_validation(PdfValidator().validate(path, depth=ValidationDepth.DEEP))
    assert result.structural is CheckStatus.FAILED
    assert EvidenceCode.STRUCTURAL_FAILURE in result.codes
