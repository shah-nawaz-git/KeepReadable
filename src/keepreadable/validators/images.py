import warnings
from pathlib import Path
from typing import Any

from PIL import Image, ImageSequence, UnidentifiedImageError
from PIL import __version__ as pillow_version

from keepreadable.domain.enums import CheckStatus, SupportTier
from keepreadable.utilities.cancellation import CancellationToken
from keepreadable.utilities.filesystem import extended_path
from keepreadable.validators.base import (
    EvidenceCode,
    ValidationDepth,
    ValidationResult,
    guard_validation,
)

_BITS_BY_MODE = {
    "1": 1,
    "L": 8,
    "P": 8,
    "RGB": 24,
    "RGBA": 32,
    "CMYK": 32,
    "I;16": 16,
    "I": 32,
    "F": 32,
}
_TRUNCATION_TEXT = (
    "image file is truncated",
    "broken data stream",
    "unexpected end",
    "truncated file",
)


class PillowImageValidator:
    name = "pillow-image"
    tier = SupportTier.DEEP

    def version(self) -> str:
        return pillow_version

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
        captured: list[warnings.WarningMessage]
        details: dict[str, Any] = {}
        opened = False
        try:
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter("always")
                with Image.open(extended_path(path)) as image:
                    opened = True
                    details = self._basic_details(image)
                    image.verify()
                with Image.open(extended_path(path)) as image:
                    details.update(self._metadata_details(image))
                bomb_warning = next(
                    (
                        str(item.message)
                        for item in captured
                        if issubclass(item.category, Image.DecompressionBombWarning)
                    ),
                    None,
                )
                if bomb_warning is not None:
                    return self._limited(depth, details, bomb_warning)
                if depth is ValidationDepth.DEEP:
                    frame_count = self._decode_frames(path, cancel)
                    details["frame_count"] = frame_count
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            return self._limited(depth, details, str(exc))
        except (UnidentifiedImageError, SyntaxError) as exc:
            return self._failure(
                depth,
                details,
                CheckStatus.PASSED if opened else CheckStatus.FAILED,
                CheckStatus.FAILED if opened else CheckStatus.NOT_CHECKED,
                (
                    "Image data could not be decoded."
                    if opened
                    else "Image structure could not be read."
                ),
                EvidenceCode.DECODE_FAILURE if opened else EvidenceCode.STRUCTURAL_FAILURE,
                exc,
            )
        except OSError as exc:
            message = str(exc).casefold()
            truncation = any(value in message for value in _TRUNCATION_TEXT)
            return self._failure(
                depth,
                details,
                CheckStatus.PASSED if opened else CheckStatus.FAILED,
                CheckStatus.FAILED if opened else CheckStatus.NOT_CHECKED,
                (
                    "Image decoding ended before all requested data was read."
                    if truncation
                    else "Image pixel data could not be decoded."
                )
                if opened
                else "Image structure could not be read.",
                (EvidenceCode.UNEXPECTED_TRUNCATION if truncation else EvidenceCode.DECODE_FAILURE)
                if opened
                else EvidenceCode.STRUCTURAL_FAILURE,
                exc,
            )

        warning_text = tuple(str(item.message) for item in captured)
        warning_codes = (EvidenceCode.VALIDATION_WARNING,) if warning_text else ()
        structural = CheckStatus.WARNING if warning_text else CheckStatus.PASSED
        readability = (
            CheckStatus.PASSED if depth is ValidationDepth.DEEP else CheckStatus.NOT_CHECKED
        )
        return ValidationResult(
            validator_name=self.name,
            validator_version=self.version(),
            tier=self.tier,
            depth=depth,
            structural=structural,
            readability=readability,
            summary=(
                "Image structure and pixel data were read."
                if depth is ValidationDepth.DEEP
                else "Image structure was read without decoding all pixel data."
            ),
            details=details,
            warnings=warning_text,
            errors=(),
            codes=warning_codes,
            checks_performed=(
                ("image structure", "image verification", "full pixel decode")
                if depth is ValidationDepth.DEEP
                else ("image structure", "image verification")
            ),
            checks_not_performed=(() if depth is ValidationDepth.DEEP else ("full pixel decode",)),
        )

    @staticmethod
    def _basic_details(image: Image.Image) -> dict[str, Any]:
        return {
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
            "format": image.format,
            "bit_depth": _BITS_BY_MODE.get(image.mode),
        }

    @staticmethod
    def _metadata_details(image: Image.Image) -> dict[str, Any]:
        bit_depth: int | list[int] | None = _BITS_BY_MODE.get(image.mode)
        if image.format == "TIFF" and hasattr(image, "tag_v2"):
            bits = image.tag_v2.get(258)
            if isinstance(bits, tuple):
                bit_depth = [int(value) for value in bits]
            elif isinstance(bits, int):
                bit_depth = bits
        return {
            "bit_depth": bit_depth,
            "frame_count": int(getattr(image, "n_frames", 1)),
            "has_exif": bool(image.getexif()),
            "has_icc_profile": bool(image.info.get("icc_profile")),
        }

    @staticmethod
    def _decode_frames(path: Path, cancel: CancellationToken | None) -> int:
        count = 0
        with Image.open(extended_path(path)) as image:
            for frame in ImageSequence.Iterator(image):
                if cancel is not None:
                    cancel.raise_if_cancelled()
                frame.load()
                count += 1
        return count

    def _limited(
        self, depth: ValidationDepth, details: dict[str, Any], message: str
    ) -> ValidationResult:
        return ValidationResult(
            self.name,
            self.version(),
            self.tier,
            depth,
            CheckStatus.NOT_CHECKED,
            CheckStatus.NOT_CHECKED,
            "Image dimensions exceeded the configured decode safety limit.",
            details,
            (),
            (message,),
            (EvidenceCode.VALIDATION_LIMITED,),
            (),
            ("image structure", "full pixel decode"),
        )

    def _failure(
        self,
        depth: ValidationDepth,
        details: dict[str, Any],
        structural: CheckStatus,
        readability: CheckStatus,
        summary: str,
        code: EvidenceCode,
        error: Exception,
    ) -> ValidationResult:
        return ValidationResult(
            self.name,
            self.version(),
            self.tier,
            depth,
            structural,
            readability,
            summary,
            details,
            (),
            (repr(error),),
            (code,),
            ("image structure",),
            ("full pixel decode",),
        )
