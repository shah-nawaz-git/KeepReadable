from pathlib import Path

import pytest

from keepreadable.domain.enums import CheckStatus, SupportTier
from keepreadable.utilities.cancellation import CancellationToken, OperationCancelled
from keepreadable.validators.base import (
    EvidenceCode,
    ValidationDepth,
    ValidationResult,
    guard_validation,
    not_supported_result,
    unavailable_result,
)


class CrashingValidator:
    name = "crashing"
    tier = SupportTier.DEEP

    def version(self) -> str:
        return "1"

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
        raise RuntimeError("validator failure")


def test_guard_converts_unexpected_error_without_file_claim() -> None:
    result = CrashingValidator().validate(Path("file"), depth=ValidationDepth.DEEP)
    assert result.structural is CheckStatus.NOT_CHECKED
    assert result.readability is CheckStatus.NOT_CHECKED
    assert result.summary == "This file could not be checked."
    assert result.codes == (EvidenceCode.VALIDATION_LIMITED,)
    assert "RuntimeError" in result.errors[0]


def test_guard_propagates_cancellation() -> None:
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelled):
        CrashingValidator().validate(Path("file"), depth=ValidationDepth.DEEP, cancel=token)


def test_unavailable_and_not_supported_results() -> None:
    unavailable = unavailable_result(
        "tool", SupportTier.DEEP, ValidationDepth.DEEP, "Tool is unavailable."
    )
    unsupported = not_supported_result("identify", SupportTier.IDENTIFY_ONLY, ValidationDepth.DEEP)
    assert unavailable.structural is CheckStatus.UNAVAILABLE
    assert unavailable.codes == (EvidenceCode.TOOL_UNAVAILABLE,)
    assert unsupported.structural is CheckStatus.NOT_CHECKED
    assert unsupported.codes == (EvidenceCode.NOT_SUPPORTED,)
