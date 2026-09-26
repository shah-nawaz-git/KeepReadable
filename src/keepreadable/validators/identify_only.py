from pathlib import Path

from keepreadable.domain.enums import SupportTier
from keepreadable.utilities.cancellation import CancellationToken
from keepreadable.validators.base import (
    ValidationDepth,
    ValidationResult,
    not_supported_result,
)


class IdentifyOnlyValidator:
    name = "identify-only"
    tier = SupportTier.IDENTIFY_ONLY

    def version(self) -> str:
        return "1"

    def validate(
        self,
        path: Path,
        *,
        depth: ValidationDepth,
        cancel: CancellationToken | None = None,
    ) -> ValidationResult:
        if cancel is not None:
            cancel.raise_if_cancelled()
        return not_supported_result(self.name, self.tier, depth)
