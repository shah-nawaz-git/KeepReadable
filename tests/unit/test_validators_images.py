from collections.abc import Callable
from pathlib import Path

import pytest

from keepreadable.domain.enums import CheckStatus
from keepreadable.validators.base import EvidenceCode, ValidationDepth, ValidationResult
from keepreadable.validators.images import PillowImageValidator
from tests.fixture_factory import (
    flip_bytes,
    make_bmp,
    make_jpeg,
    make_jpeg_with_exif,
    make_multiframe_tiff,
    make_png,
    make_tiff,
    truncate_file,
)


@pytest.mark.parametrize(
    ("factory", "extension", "format_name"),
    [
        (make_jpeg, "jpg", "JPEG"),
        (make_png, "png", "PNG"),
        (make_tiff, "tiff", "TIFF"),
        (make_bmp, "bmp", "BMP"),
    ],
)
def test_healthy_images_deep_decode(
    tmp_path: Path,
    factory: Callable[..., Path],
    extension: str,
    format_name: str,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    path = factory(tmp_path / f"image.{extension}", size=(64, 48), seed=3)
    result = record_validation(PillowImageValidator().validate(path, depth=ValidationDepth.DEEP))
    assert result.structural is CheckStatus.PASSED
    assert result.readability is CheckStatus.PASSED
    assert result.details["width"] == 64
    assert result.details["height"] == 48
    assert result.details["mode"] == "RGB"
    assert result.details["format"] == format_name
    assert "full pixel decode" in result.checks_performed


def test_quick_does_not_decode_all_pixels(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    result = record_validation(
        PillowImageValidator().validate(
            make_png(tmp_path / "image.png"), depth=ValidationDepth.QUICK
        )
    )
    assert result.structural is CheckStatus.PASSED
    assert result.readability is CheckStatus.NOT_CHECKED
    assert "full pixel decode" in result.checks_not_performed


def test_truncated_jpeg_reports_truncation(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    path = truncate_file(make_jpeg(tmp_path / "truncated.jpg"), 0.65)
    result = record_validation(PillowImageValidator().validate(path, depth=ValidationDepth.DEEP))
    assert result.readability is CheckStatus.FAILED
    assert EvidenceCode.UNEXPECTED_TRUNCATION in result.codes


def test_png_with_changed_idat_fails_decode(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    path = make_png(tmp_path / "changed.png")
    data = path.read_bytes()
    position = data.index(b"IDAT") + 8
    flip_bytes(path, position, 12, seed=4)
    result = record_validation(PillowImageValidator().validate(path, depth=ValidationDepth.DEEP))
    assert result.readability is CheckStatus.FAILED
    assert (
        EvidenceCode.DECODE_FAILURE in result.codes
        or EvidenceCode.UNEXPECTED_TRUNCATION in result.codes
    )


def test_garbage_named_png_is_structural_failure(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    path = tmp_path / "garbage.png"
    path.write_bytes(b"not an image")
    result = record_validation(PillowImageValidator().validate(path, depth=ValidationDepth.DEEP))
    assert result.structural is CheckStatus.FAILED
    assert EvidenceCode.STRUCTURAL_FAILURE in result.codes


def test_multiframe_tiff_and_exif_details(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    tiff = record_validation(
        PillowImageValidator().validate(
            make_multiframe_tiff(tmp_path / "frames.tiff"), depth=ValidationDepth.DEEP
        )
    )
    exif = record_validation(
        PillowImageValidator().validate(
            make_jpeg_with_exif(tmp_path / "exif.jpg"), depth=ValidationDepth.DEEP
        )
    )
    assert tiff.details["frame_count"] == 3
    assert exif.details["has_exif"] is True


@pytest.mark.parametrize("kind", ["garbage", "empty", "directory"])
def test_validator_never_raises_for_bad_inputs(
    tmp_path: Path,
    kind: str,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    path = tmp_path / kind
    if kind == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"garbage" if kind == "garbage" else b"")
    result = record_validation(PillowImageValidator().validate(path, depth=ValidationDepth.DEEP))
    assert isinstance(result, ValidationResult)
