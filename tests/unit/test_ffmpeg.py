from pathlib import Path
from typing import Any

import pytest

from keepreadable.integrations.ffmpeg import FFmpegAdapter, FFprobeError, parse_ffprobe_json
from keepreadable.integrations.subprocess_runner import CommandResult, ToolNotFoundError

FIXTURE = Path(__file__).parents[1] / "fixtures" / "ffprobe_sample.json"


def result(
    args: list[str],
    *,
    returncode: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
    timed_out: bool = False,
) -> CommandResult:
    return CommandResult(tuple(args), returncode, stdout, stderr, 0.25, timed_out)


def test_parse_ffprobe_fixture_has_typed_streams() -> None:
    probe = parse_ffprobe_json(FIXTURE.read_bytes())
    assert probe.format_name == "mov,mp4,m4a,3gp,3g2,mj2"
    assert probe.duration == 1.0
    assert probe.size == 12750
    assert len(probe.video_streams) == 1
    assert probe.video_streams[0].width == 64
    assert probe.video_streams[0].nb_frames == 10
    assert len(probe.audio_streams) == 1
    assert probe.audio_streams[0].sample_rate == 44100
    assert probe.audio_streams[0].channels == 1


def test_probe_uses_file_protocol_and_parses(tmp_path: Path) -> None:
    def runner(args: list[str], **kwargs: Any) -> CommandResult:
        assert args[-2] == "-i"
        assert args[-1].startswith("file:")
        assert kwargs["timeout"] == 20
        return result(args, stdout=FIXTURE.read_bytes())

    adapter = FFmpegAdapter(
        tmp_path / "ffmpeg.exe", tmp_path / "ffprobe.exe", runner=runner, timeout=20
    )
    assert adapter.probe(tmp_path / "odd & name.mp4").video_streams[0].codec_name == "h264"


def test_decode_result_maps_failure_and_stderr(tmp_path: Path) -> None:
    def runner(args: list[str], **_kwargs: Any) -> CommandResult:
        assert "-xerror" in args
        return result(args, returncode=1, stderr=b"first error\nsecond error\n")

    decoded = FFmpegAdapter(tmp_path / "ffmpeg.exe", None, runner=runner).decode_to_null(
        tmp_path / "bad.mp4"
    )
    assert not decoded.success
    assert decoded.returncode == 1
    assert decoded.error_lines == ("first error", "second error")
    assert decoded.duration_seconds == 0.25


def test_probe_failure_uses_stderr_tail(tmp_path: Path) -> None:
    def runner(args: list[str], **_kwargs: Any) -> CommandResult:
        return result(args, returncode=1, stderr=b"invalid media")

    adapter = FFmpegAdapter(None, tmp_path / "ffprobe.exe", runner=runner)
    with pytest.raises(FFprobeError, match="invalid media"):
        adapter.probe(tmp_path / "bad.mp4")


def test_probe_timeout_raises(tmp_path: Path) -> None:
    def runner(args: list[str], **_kwargs: Any) -> CommandResult:
        return result(args, timed_out=True)

    with pytest.raises(FFprobeError, match="timed out"):
        FFmpegAdapter(None, tmp_path / "ffprobe.exe", runner=runner).probe(tmp_path / "file.mp4")


def test_missing_tools_raise_or_return_none(tmp_path: Path) -> None:
    adapter = FFmpegAdapter(None, None)
    assert adapter.version() is None
    with pytest.raises(ToolNotFoundError):
        adapter.probe(tmp_path / "file.mp4")
    with pytest.raises(ToolNotFoundError):
        adapter.decode_to_null(tmp_path / "file.mp4")
    with pytest.raises(ToolNotFoundError):
        adapter.run(["-version"])


def test_version_and_generic_run(tmp_path: Path) -> None:
    def runner(args: list[str], **_kwargs: Any) -> CommandResult:
        if "-version" in args:
            return result(args, stdout=b"ffmpeg version 8.1.2-essentials_build-www.gyan.dev\n")
        return result(args)

    adapter = FFmpegAdapter(tmp_path / "ffmpeg.exe", None, runner=runner)
    assert adapter.version() == "8.1.2-essentials_build-www.gyan.dev"
    command = adapter.run(["-i", "input", "output"])
    assert command.args[1:] == ("-i", "input", "output")
