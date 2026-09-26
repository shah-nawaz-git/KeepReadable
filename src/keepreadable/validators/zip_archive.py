import platform
import re
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from keepreadable.domain.enums import CheckStatus, SupportTier
from keepreadable.utilities.cancellation import CancellationToken
from keepreadable.utilities.filesystem import extended_path
from keepreadable.validators.base import (
    EvidenceCode,
    ValidationDepth,
    ValidationResult,
    guard_validation,
)


class ZipValidator:
    name = "zipfile"
    tier = SupportTier.DEEP

    def __init__(
        self,
        max_entries: int,
        max_declared_size_bytes: int,
        suspicious_ratio: float,
    ) -> None:
        self.max_entries = max_entries
        self.max_declared_size_bytes = max_declared_size_bytes
        self.suspicious_ratio = suspicious_ratio

    def version(self) -> str:
        return platform.python_version()

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
        try:
            archive = zipfile.ZipFile(extended_path(path))
        except (zipfile.BadZipFile, OSError) as exc:
            return self._structural_failure(depth, exc)
        with archive:
            try:
                entries = archive.infolist()
            except (zipfile.BadZipFile, OSError) as exc:
                return self._structural_failure(depth, exc)
            details, warning_text = self._inspect(entries)
            encrypted = int(details["encrypted_entries"])
            codes: list[EvidenceCode] = []
            if warning_text:
                codes.append(EvidenceCode.VALIDATION_WARNING)
            if encrypted:
                codes.append(EvidenceCode.PROTECTED_CONTENT)
                return ValidationResult(
                    self.name,
                    self.version(),
                    self.tier,
                    depth,
                    CheckStatus.PASSED,
                    CheckStatus.PROTECTED,
                    "Encrypted entries detected. Contents were not deeply validated.",
                    details,
                    tuple(warning_text),
                    (),
                    tuple(codes),
                    ("ZIP structure", "entry metadata"),
                    ("entry CRC checks",),
                )
            readability = CheckStatus.NOT_CHECKED
            checks = ["ZIP structure", "entry metadata"]
            not_performed: tuple[str, ...] = ("entry CRC checks",)
            if depth is ValidationDepth.DEEP:
                if cancel is not None:
                    cancel.raise_if_cancelled()
                errors: tuple[str, ...]
                try:
                    bad_member = archive.testzip()
                except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
                    bad_member = "unknown"
                    errors = (repr(exc),)
                else:
                    errors = ()
                checks.append("entry CRC checks")
                not_performed = ()
                if bad_member is not None:
                    details["crc_failed_member"] = bad_member
                    return ValidationResult(
                        self.name,
                        self.version(),
                        self.tier,
                        depth,
                        CheckStatus.PASSED,
                        CheckStatus.FAILED,
                        "CRC check failed for 1 entry.",
                        details,
                        tuple(warning_text),
                        errors,
                        tuple([*codes, EvidenceCode.DECODE_FAILURE]),
                        tuple(checks),
                        not_performed,
                    )
                readability = CheckStatus.PASSED
            return ValidationResult(
                self.name,
                self.version(),
                self.tier,
                depth,
                CheckStatus.PASSED,
                readability,
                (
                    "ZIP structure and entry CRC values were checked."
                    if depth is ValidationDepth.DEEP
                    else "ZIP structure and entry metadata were checked."
                ),
                details,
                tuple(warning_text),
                (),
                tuple(codes),
                tuple(checks),
                not_performed,
            )

    def _inspect(self, entries: list[zipfile.ZipInfo]) -> tuple[dict[str, Any], list[str]]:
        declared = sum(entry.file_size for entry in entries)
        compressed = sum(entry.compress_size for entry in entries)
        encrypted = sum(bool(entry.flag_bits & 1) for entry in entries)
        ratios = [
            entry.file_size / entry.compress_size for entry in entries if entry.compress_size > 0
        ]
        suspicious = [
            entry.filename
            for entry in entries
            if entry.file_size > 1 << 20
            and entry.compress_size > 0
            and entry.file_size / entry.compress_size > self.suspicious_ratio
        ]
        unsafe_names = [
            entry.orig_filename for entry in entries if self._unsafe_name(entry.orig_filename)
        ]
        warnings_found: list[str] = []
        if len(entries) > self.max_entries:
            warnings_found.append("entry count exceeds the configured validation limit")
        if declared > self.max_declared_size_bytes:
            warnings_found.append(
                "declared uncompressed size exceeds the configured validation limit"
            )
        if suspicious:
            warnings_found.append("suspicious compression ratio")
        if unsafe_names:
            warnings_found.append("entry names that could escape a destination folder")
        return (
            {
                "entry_count": len(entries),
                "declared_uncompressed_bytes": declared,
                "compressed_bytes": compressed,
                "encrypted_entries": encrypted,
                "max_compression_ratio": max(ratios, default=0.0),
                "suspicious_ratio_entries": suspicious,
                "unsafe_entry_names": unsafe_names,
            },
            warnings_found,
        )

    @staticmethod
    def _unsafe_name(name: str) -> bool:
        normalized = name.replace("\\", "/")
        parts = PurePosixPath(normalized).parts
        windows = PureWindowsPath(name)
        return bool(
            "\0" in name
            or name.startswith(("/", "\\"))
            or windows.drive
            or ".." in parts
            or re.match(r"^[A-Za-z]:", name)
        )

    def _structural_failure(self, depth: ValidationDepth, error: Exception) -> ValidationResult:
        return ValidationResult(
            self.name,
            self.version(),
            self.tier,
            depth,
            CheckStatus.FAILED,
            CheckStatus.NOT_CHECKED,
            "ZIP structure could not be read.",
            {},
            (),
            (repr(error),),
            (EvidenceCode.STRUCTURAL_FAILURE,),
            ("ZIP structure",),
            ("entry CRC checks",),
        )
