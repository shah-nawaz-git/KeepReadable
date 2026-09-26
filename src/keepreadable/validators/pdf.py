import logging
from pathlib import Path
from typing import Any, Protocol, cast

import pikepdf
from pypdf import PdfReader

from keepreadable.domain.enums import CheckStatus, SupportTier
from keepreadable.utilities.cancellation import CancellationToken
from keepreadable.utilities.filesystem import extended_path
from keepreadable.validators.base import (
    EvidenceCode,
    ValidationDepth,
    ValidationResult,
    guard_validation,
)


class _CheckablePdf(Protocol):
    def check_pdf_syntax(self) -> list[str]: ...


class _MessageHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class PdfValidator:
    name = "pikepdf-pypdf"
    tier = SupportTier.DEEP

    def version(self) -> str:
        return f"pikepdf {pikepdf.__version__}"

    @guard_validation
    def validate(
        self,
        path: Path,
        *,
        depth: ValidationDepth,
        cancel: CancellationToken | None = None,
    ) -> ValidationResult:
        if cancel is not None:
            cancel.raise_if_cancelled()
        header, eof_found = self._markers(path)
        details: dict[str, Any] = {
            "header_version": header.decode("ascii", errors="replace") if header else None,
            "eof_marker_found": eof_found,
        }
        warnings_found = (
            [] if eof_found else ["end-of-file marker not found; the file may be truncated"]
        )
        codes = [] if eof_found else [EvidenceCode.VALIDATION_WARNING]
        if header is None:
            return self._structural_failure(
                depth, details, ValueError("PDF header not found"), eof_found
            )
        try:
            with pikepdf.open(extended_path(path)) as pdf:
                details.update(self._details(pdf))
                if depth is ValidationDepth.DEEP:
                    return self._deep(pdf, path, details, warnings_found, codes, cancel)
        except pikepdf.PasswordError as exc:
            details["is_encrypted"] = True
            return ValidationResult(
                self.name,
                self.version(),
                self.tier,
                depth,
                CheckStatus.PASSED,
                CheckStatus.PROTECTED,
                "Password protection prevented page content checks.",
                details,
                tuple(warnings_found),
                (repr(exc),),
                tuple([*codes, EvidenceCode.PROTECTED_CONTENT]),
                ("PDF header", "end-of-file marker"),
                ("page content access", "PDF/A or ISO conformance validation"),
            )
        except pikepdf.PdfError as exc:
            return self._structural_failure(depth, details, exc, eof_found)
        return ValidationResult(
            self.name,
            self.version(),
            self.tier,
            depth,
            CheckStatus.PASSED,
            CheckStatus.NOT_CHECKED,
            (
                "PDF markers and object structure were checked; "
                "PDF/A or ISO conformance was not checked."
            ),
            details,
            tuple(warnings_found),
            (),
            tuple(codes),
            ("PDF header", "end-of-file marker", "PDF object structure", "page count"),
            ("page content access", "PDF/A or ISO conformance validation"),
        )

    @staticmethod
    def _markers(path: Path) -> tuple[bytes | None, bool]:
        path_value = extended_path(path)
        with open(path_value, "rb") as stream:
            first = stream.read(1024)
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - 2048))
            tail = stream.read(2048)
        position = first.find(b"%PDF-")
        header = first[position : position + 8] if position >= 0 else None
        return header, b"%%EOF" in tail

    @staticmethod
    def _details(pdf: pikepdf.Pdf) -> dict[str, Any]:
        producer_value = pdf.docinfo.get("/Producer")
        producer = str(producer_value) if producer_value is not None else None
        return {
            "page_count": len(pdf.pages),
            "pdf_version": str(pdf.pdf_version),
            "is_encrypted": bool(pdf.is_encrypted),
            "has_xmp_metadata": "/Metadata" in pdf.Root,
            "producer": producer,
        }

    def _deep(
        self,
        pdf: pikepdf.Pdf,
        path: Path,
        details: dict[str, Any],
        warnings_found: list[str],
        codes: list[EvidenceCode],
        cancel: CancellationToken | None,
    ) -> ValidationResult:
        check_messages = [str(message) for message in cast(_CheckablePdf, pdf).check_pdf_syntax()]
        warnings_found.extend(check_messages)
        try:
            for page in pdf.pages:
                if cancel is not None:
                    cancel.raise_if_cancelled()
                page.obj.get("/Contents")
                page.obj.get("/Resources")
                page.obj.get("/MediaBox")
        except Exception as exc:
            return ValidationResult(
                self.name,
                self.version(),
                self.tier,
                ValidationDepth.DEEP,
                CheckStatus.PASSED,
                CheckStatus.FAILED,
                "A PDF page object could not be read.",
                details,
                tuple(warnings_found),
                (repr(exc),),
                (EvidenceCode.DECODE_FAILURE,),
                ("PDF object structure", "page content access"),
                ("PDF/A or ISO conformance validation",),
            )
        handler = _MessageHandler()
        logger = logging.getLogger("pypdf")
        logger.addHandler(handler)
        try:
            with open(extended_path(path), "rb") as stream:
                reader = PdfReader(stream, strict=False)
                pypdf_count = len(reader.pages)
        except Exception as exc:
            warnings_found.extend(handler.messages)
            text = str(exc).casefold()
            truncation = any(value in text for value in ("end", "eof", "truncat"))
            return ValidationResult(
                self.name,
                self.version(),
                self.tier,
                ValidationDepth.DEEP,
                CheckStatus.PASSED,
                CheckStatus.FAILED,
                "Independent PDF page reading ended before completion."
                if truncation
                else "Independent PDF page reading could not be completed.",
                details,
                tuple(warnings_found),
                (repr(exc),),
                (
                    EvidenceCode.UNEXPECTED_TRUNCATION
                    if truncation
                    else EvidenceCode.DECODE_FAILURE,
                ),
                ("PDF object structure", "independent page count"),
                ("PDF/A or ISO conformance validation",),
            )
        finally:
            logger.removeHandler(handler)
        warnings_found.extend(handler.messages)
        details["pypdf_page_count"] = pypdf_count
        if pypdf_count != details["page_count"]:
            warnings_found.append("page counts differed between PDF readers")
        if warnings_found and EvidenceCode.VALIDATION_WARNING not in codes:
            codes.append(EvidenceCode.VALIDATION_WARNING)
        return ValidationResult(
            self.name,
            self.version(),
            self.tier,
            ValidationDepth.DEEP,
            CheckStatus.PASSED,
            CheckStatus.PASSED,
            "PDF objects were read; PDF/A or ISO conformance was not checked.",
            details,
            tuple(warnings_found),
            (),
            tuple(codes),
            (
                "PDF header",
                "end-of-file marker",
                "PDF object structure",
                "pikepdf consistency checks",
                "page content access",
                "independent page count",
            ),
            ("PDF/A or ISO conformance validation",),
        )

    def _structural_failure(
        self,
        depth: ValidationDepth,
        details: dict[str, Any],
        error: Exception,
        eof_found: bool,
    ) -> ValidationResult:
        text = str(error).casefold()
        truncation = not eof_found and any(
            value in text for value in ("end of file", "xref", "trailer", "eof")
        )
        codes = [EvidenceCode.STRUCTURAL_FAILURE]
        if truncation:
            codes.append(EvidenceCode.UNEXPECTED_TRUNCATION)
        return ValidationResult(
            self.name,
            self.version(),
            self.tier,
            depth,
            CheckStatus.FAILED,
            CheckStatus.NOT_CHECKED,
            "PDF object structure could not be read.",
            details,
            (),
            (repr(error),),
            tuple(codes),
            ("PDF header", "end-of-file marker", "PDF object structure"),
            ("page content access", "PDF/A or ISO conformance validation"),
        )
