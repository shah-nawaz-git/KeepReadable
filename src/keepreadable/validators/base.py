from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum, auto
from functools import wraps
from pathlib import Path
from typing import Any, Protocol, cast

from keepreadable.domain.enums import CheckStatus, SupportTier
from keepreadable.utilities.cancellation import CancellationToken, OperationCancelled


class ValidationDepth(StrEnum):
    QUICK = auto()
    DEEP = auto()


class EvidenceCode(StrEnum):
    STRUCTURAL_FAILURE = auto()
    DECODE_FAILURE = auto()
    UNEXPECTED_TRUNCATION = auto()
    VALIDATION_WARNING = auto()
    PROTECTED_CONTENT = auto()
    TOOL_UNAVAILABLE = auto()
    VALIDATION_LIMITED = auto()
    NOT_SUPPORTED = auto()


@dataclass(frozen=True, slots=True)
class ValidationResult:
    validator_name: str
    validator_version: str
    tier: SupportTier
    depth: ValidationDepth
    structural: CheckStatus
    readability: CheckStatus
    summary: str
    details: dict[str, Any]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    codes: tuple[EvidenceCode, ...]
    checks_performed: tuple[str, ...]
    checks_not_performed: tuple[str, ...]


class Validator(Protocol):
    name: str
    tier: SupportTier

    def version(self) -> str: ...

    def validate(
        self,
        path: Path,
        *,
        depth: ValidationDepth,
        cancel: CancellationToken | None = None,
    ) -> ValidationResult: ...


def unavailable_result(
    name: str, tier: SupportTier, depth: ValidationDepth, reason: str
) -> ValidationResult:
    return ValidationResult(
        validator_name=name,
        validator_version="",
        tier=tier,
        depth=depth,
        structural=CheckStatus.UNAVAILABLE,
        readability=CheckStatus.UNAVAILABLE,
        summary=reason,
        details={},
        warnings=(),
        errors=(),
        codes=(EvidenceCode.TOOL_UNAVAILABLE,),
        checks_performed=(),
        checks_not_performed=("structural validation", "readability validation"),
    )


def not_supported_result(name: str, tier: SupportTier, depth: ValidationDepth) -> ValidationResult:
    return ValidationResult(
        validator_name=name,
        validator_version="",
        tier=tier,
        depth=depth,
        structural=CheckStatus.NOT_CHECKED,
        readability=CheckStatus.NOT_CHECKED,
        summary="Deep readability validation is not currently available for this format.",
        details={},
        warnings=(),
        errors=(),
        codes=(EvidenceCode.NOT_SUPPORTED,),
        checks_performed=(),
        checks_not_performed=("structural validation", "readability validation"),
    )


def guard_validation[ValidationCallable: Callable[..., ValidationResult]](
    function: ValidationCallable,
) -> ValidationCallable:
    @wraps(function)
    def guarded(
        self: Validator,
        path: Path,
        *,
        depth: ValidationDepth,
        cancel: CancellationToken | None = None,
    ) -> ValidationResult:
        try:
            return function(self, path, depth=depth, cancel=cancel)
        except OperationCancelled:
            raise
        except Exception as exc:
            return ValidationResult(
                validator_name=self.name,
                validator_version=self.version(),
                tier=self.tier,
                depth=depth,
                structural=CheckStatus.NOT_CHECKED,
                readability=CheckStatus.NOT_CHECKED,
                summary="This file could not be checked.",
                details={},
                warnings=(),
                errors=(repr(exc),),
                codes=(EvidenceCode.VALIDATION_LIMITED,),
                checks_performed=(),
                checks_not_performed=("structural validation", "readability validation"),
            )

    return cast(ValidationCallable, guarded)
