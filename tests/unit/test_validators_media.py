from pathlib import Path
from typing import Any

import pytest

from keepreadable.domain.enums import CheckStatus
from keepreadable.integrations.ffmpeg import FFmpegAdapter
from keepreadable.integrations.subprocess_runner import CommandResult
from keepreadable.utilities.cancellation import CancellationToken, OperationCancelled
from keepreadable.validators.base import EvidenceCode, ValidationDepth
from keepreadable.validators.media import FFmpegMediaValidator

PROBE_JSON = (
    b'{"streams":[{"index":0,"codec_type":"video","codec_name":"h264",'
    b'"width":64,"height":64}],"format":{"format_name":"mp4","duration":"1.0"}}'
)


def command(
    args: list[str],
    *,
    returncode: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
    timed_out: bool = False,
) -> CommandResult:
    return CommandResult(tuple(args), returncode, stdout, stderr, 0.2, timed_out)


def test_adapter_none_is_unavailable() -> None:
    result = FFmpegMediaValidator(None).validate(Path("media.mp4"), depth=ValidationDepth.DEEP)
    assert result.structural is CheckStatus.UNAVAILABLE
    assert result.readability is CheckStatus.UNAVAILABLE
    assert EvidenceCode.TOOL_UNAVAILABLE in result.codes


def test_timed_out_decode_is_limited(tmp_path: Path) -> None:
    def runner(args: list[str], **_kwargs: Any) -> CommandResult:
        if "-version" in args:
            return command(args, stdout=b"ffmpeg version 8.1.2\n")
        if "-print_format" in args:
            return command(args, stdout=PROBE_JSON)
        return command(args, timed_out=True)

    adapter = FFmpegAdapter(tmp_path / "ffmpeg.exe", tmp_path / "ffprobe.exe", runner=runner)
    result = FFmpegMediaValidator(adapter).validate(
        tmp_path / "media.mp4", depth=ValidationDepth.DEEP
    )
    assert result.structural is CheckStatus.PASSED
    assert result.readability is CheckStatus.NOT_CHECKED
    assert EvidenceCode.VALIDATION_LIMITED in result.codes


def test_probe_and_decode_failures_map_evidence(tmp_path: Path) -> None:
    def probe_failure(args: list[str], **_kwargs: Any) -> CommandResult:
        if "-version" in args:
            return command(args, stdout=b"ffmpeg version 8.1.2\n")
        return command(args, returncode=1, stderr=b"moov atom not found")

    probe_result = FFmpegMediaValidator(
        FFmpegAdapter(tmp_path / "ffmpeg.exe", tmp_path / "ffprobe.exe", runner=probe_failure)
    ).validate(tmp_path / "media.mp4", depth=ValidationDepth.DEEP)
    assert probe_result.structural is CheckStatus.FAILED
    assert EvidenceCode.UNEXPECTED_TRUNCATION in probe_result.codes

    def decode_failure(args: list[str], **_kwargs: Any) -> CommandResult:
        if "-version" in args:
            return command(args, stdout=b"ffmpeg version 8.1.2\n")
        if "-print_format" in args:
            return command(args, stdout=PROBE_JSON)
        return command(args, returncode=1, stderr=b"stream decode error")

    decode_result = FFmpegMediaValidator(
        FFmpegAdapter(tmp_path / "ffmpeg.exe", tmp_path / "ffprobe.exe", runner=decode_failure)
    ).validate(tmp_path / "media.mp4", depth=ValidationDepth.DEEP)
    assert decode_result.structural is CheckStatus.PASSED
    assert decode_result.readability is CheckStatus.FAILED
    assert EvidenceCode.DECODE_FAILURE in decode_result.codes


def test_cancellation_propagates(tmp_path: Path) -> None:
    token = CancellationToken()

    def runner(_args: list[str], **_kwargs: Any) -> CommandResult:
        raise OperationCancelled

    adapter = FFmpegAdapter(tmp_path / "ffmpeg.exe", tmp_path / "ffprobe.exe", runner=runner)
    with pytest.raises(OperationCancelled):
        FFmpegMediaValidator(adapter).validate(
            tmp_path / "media.mp4", depth=ValidationDepth.DEEP, cancel=token
        )
