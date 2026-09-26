from collections.abc import Callable
from pathlib import Path

import pytest

from keepreadable.domain.enums import CheckStatus
from keepreadable.integrations.ffmpeg import FFmpegAdapter
from keepreadable.integrations.tool_locator import ToolLocator, ToolName
from keepreadable.validators.base import EvidenceCode, ValidationDepth, ValidationResult
from keepreadable.validators.media import FFmpegMediaValidator
from tests.fixture_factory import (
    make_avi,
    make_flac,
    make_mov,
    make_mp3,
    make_mp4,
    make_wav,
    truncate_file,
    zero_range,
)

pytestmark = pytest.mark.external_tools


def media_validator(locator: ToolLocator) -> FFmpegMediaValidator:
    return FFmpegMediaValidator(
        FFmpegAdapter(
            locator.locate(ToolName.FFMPEG),
            locator.locate(ToolName.FFPROBE),
            timeout=60,
        )
    )


@pytest.mark.parametrize(
    ("factory", "extension"),
    [
        (make_mp4, "mp4"),
        (make_mov, "mov"),
        (make_avi, "avi"),
        (make_mp3, "mp3"),
        (make_wav, "wav"),
        (make_flac, "flac"),
    ],
)
def test_valid_media_deep_decode(
    tmp_path: Path,
    tools_available: ToolLocator,
    factory: Callable[..., Path],
    extension: str,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    path = factory(tmp_path / f"media.{extension}")
    result = record_validation(
        media_validator(tools_available).validate(path, depth=ValidationDepth.DEEP)
    )
    assert result.structural is CheckStatus.PASSED
    assert result.readability is CheckStatus.PASSED
    assert result.details["duration_seconds"] == pytest.approx(1.0, abs=0.25)
    assert result.details["stream_count"] >= 1


def test_video_without_audio_and_multiple_audio_streams(
    tmp_path: Path,
    tools_available: ToolLocator,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    validator = media_validator(tools_available)
    silent = make_mp4(tmp_path / "silent.mp4", with_audio=False)
    silent_result = record_validation(validator.validate(silent, depth=ValidationDepth.DEEP))
    assert silent_result.details["has_video"] is True
    assert silent_result.details["has_audio"] is False

    adapter = validator.adapter
    assert adapter is not None
    multi = tmp_path / "multi-audio.mp4"
    generated = adapter.run(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=64x64:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(multi),
        ]
    )
    assert generated.returncode == 0
    multi_result = record_validation(validator.validate(multi, depth=ValidationDepth.DEEP))
    assert len(multi_result.details["audio_streams"]) == 2


def test_detected_media_damage_methods(
    tmp_path: Path,
    tools_available: ToolLocator,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    validator = media_validator(tools_available)
    truncated_mp4 = truncate_file(make_mp4(tmp_path / "truncated.mp4"), 0.6)
    truncated_wav = truncate_file(make_wav(tmp_path / "truncated.wav"), 0.6)
    mp3 = make_mp3(tmp_path / "changed.mp3", seconds=3)
    size = mp3.stat().st_size
    changed_mp3 = zero_range(mp3, size // 2 - 2048, 4096)

    mp4_result = record_validation(validator.validate(truncated_mp4, depth=ValidationDepth.DEEP))
    wav_result = record_validation(validator.validate(truncated_wav, depth=ValidationDepth.DEEP))
    mp3_result = record_validation(validator.validate(changed_mp3, depth=ValidationDepth.DEEP))

    assert (
        mp4_result.structural is CheckStatus.FAILED or mp4_result.readability is CheckStatus.FAILED
    )
    assert any(
        code in mp4_result.codes
        for code in (EvidenceCode.UNEXPECTED_TRUNCATION, EvidenceCode.DECODE_FAILURE)
    )
    assert wav_result.readability is CheckStatus.FAILED
    assert (
        EvidenceCode.UNEXPECTED_TRUNCATION in wav_result.codes
        or EvidenceCode.DECODE_FAILURE in wav_result.codes
    )
    assert mp3_result.readability is CheckStatus.FAILED
    assert EvidenceCode.DECODE_FAILURE in mp3_result.codes
