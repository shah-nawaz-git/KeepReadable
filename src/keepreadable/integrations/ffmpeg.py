import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from keepreadable.integrations.subprocess_runner import (
    CommandResult,
    Runner,
    ToolNotFoundError,
    run_command,
)
from keepreadable.utilities.cancellation import CancellationToken
from keepreadable.utilities.filesystem import extended_path


@dataclass(frozen=True, slots=True)
class StreamInfo:
    index: int
    codec_type: str
    codec_name: str | None
    codec_long_name: str | None
    width: int | None
    height: int | None
    avg_frame_rate: str | None
    r_frame_rate: str | None
    sample_rate: int | None
    channels: int | None
    duration: float | None
    bit_rate: int | None
    nb_frames: int | None
    pix_fmt: str | None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    format_name: str | None
    format_long_name: str | None
    duration: float | None
    size: int | None
    bit_rate: int | None
    streams: tuple[StreamInfo, ...]
    warnings: tuple[str, ...]

    @property
    def video_streams(self) -> tuple[StreamInfo, ...]:
        return tuple(stream for stream in self.streams if stream.codec_type == "video")

    @property
    def audio_streams(self) -> tuple[StreamInfo, ...]:
        return tuple(stream for stream in self.streams if stream.codec_type == "audio")


@dataclass(frozen=True, slots=True)
class DecodeResult:
    success: bool
    returncode: int
    error_lines: tuple[str, ...]
    duration_seconds: float
    timed_out: bool


class FFmpegError(Exception):
    pass


class FFprobeError(FFmpegError):
    pass


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: object) -> int | None:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _float(value: object) -> float | None:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_ffprobe_json(payload: bytes) -> ProbeResult:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FFprobeError("Invalid ffprobe JSON output") from exc
    if not isinstance(document, dict):
        raise FFprobeError("ffprobe output must be a JSON object")
    raw_streams = document.get("streams", [])
    raw_format = document.get("format", {})
    if not isinstance(raw_streams, list) or not isinstance(raw_format, dict):
        raise FFprobeError("ffprobe streams and format have invalid shapes")
    streams = tuple(
        StreamInfo(
            index=_integer(stream.get("index")) or 0,
            codec_type=_string(stream.get("codec_type")) or "unknown",
            codec_name=_string(stream.get("codec_name")),
            codec_long_name=_string(stream.get("codec_long_name")),
            width=_integer(stream.get("width")),
            height=_integer(stream.get("height")),
            avg_frame_rate=_string(stream.get("avg_frame_rate")),
            r_frame_rate=_string(stream.get("r_frame_rate")),
            sample_rate=_integer(stream.get("sample_rate")),
            channels=_integer(stream.get("channels")),
            duration=_float(stream.get("duration")),
            bit_rate=_integer(stream.get("bit_rate")),
            nb_frames=_integer(stream.get("nb_frames")),
            pix_fmt=_string(stream.get("pix_fmt")),
        )
        for stream in raw_streams
        if isinstance(stream, dict)
    )
    warnings_value = document.get("warnings", [])
    warnings = (
        tuple(value for value in warnings_value if isinstance(value, str))
        if isinstance(warnings_value, list)
        else ()
    )
    return ProbeResult(
        format_name=_string(raw_format.get("format_name")),
        format_long_name=_string(raw_format.get("format_long_name")),
        duration=_float(raw_format.get("duration")),
        size=_integer(raw_format.get("size")),
        bit_rate=_integer(raw_format.get("bit_rate")),
        streams=streams,
        warnings=warnings,
    )


def _stderr_tail(stderr: bytes, maximum_lines: int = 20) -> str:
    lines = stderr.decode("utf-8", errors="replace").splitlines()
    return "\n".join(lines[-maximum_lines:])


def _media_url(path: Path) -> str:
    return f"file:{extended_path(path)}"


class FFmpegAdapter:
    def __init__(
        self,
        ffmpeg: Path | None,
        ffprobe: Path | None,
        *,
        runner: Runner = run_command,
        timeout: float = 600,
    ) -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.runner = runner
        self.timeout = timeout

    def version(self) -> str | None:
        if self.ffmpeg is None:
            return None
        try:
            result = self.runner([str(self.ffmpeg), "-version"], timeout=15)
        except ToolNotFoundError:
            return None
        if result.returncode != 0 or result.timed_out:
            return None
        first_line = result.stdout.decode("utf-8", errors="replace").splitlines()
        if not first_line:
            return None
        match = re.match(r"ffmpeg version\s+([^\s]+)", first_line[0], re.IGNORECASE)
        return match.group(1) if match else None

    def probe(self, path: Path, *, cancel: CancellationToken | None = None) -> ProbeResult:
        if self.ffprobe is None:
            raise ToolNotFoundError("ffprobe is not configured")
        result = self.runner(
            [
                str(self.ffprobe),
                "-hide_banner",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                "-i",
                _media_url(path),
            ],
            timeout=self.timeout,
            cancel=cancel,
        )
        if result.timed_out:
            raise FFprobeError("ffprobe timed out")
        if result.returncode != 0:
            raise FFprobeError(_stderr_tail(result.stderr) or "ffprobe failed")
        return parse_ffprobe_json(result.stdout)

    def decode_to_null(
        self, path: Path, *, cancel: CancellationToken | None = None
    ) -> DecodeResult:
        if self.ffmpeg is None:
            raise ToolNotFoundError("ffmpeg is not configured")
        result = self.runner(
            [
                str(self.ffmpeg),
                "-hide_banner",
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-i",
                _media_url(path),
                "-f",
                "null",
                "-",
            ],
            timeout=self.timeout,
            cancel=cancel,
        )
        error_lines = tuple(
            line
            for line in result.stderr.decode("utf-8", errors="replace").splitlines()
            if line.strip()
        )[-50:]
        return DecodeResult(
            success=result.returncode == 0 and not result.timed_out,
            returncode=result.returncode,
            error_lines=error_lines,
            duration_seconds=result.duration_seconds,
            timed_out=result.timed_out,
        )

    def run(
        self,
        args: Sequence[str],
        *,
        cancel: CancellationToken | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        if self.ffmpeg is None:
            raise ToolNotFoundError("ffmpeg is not configured")
        return self.runner(
            [str(self.ffmpeg), *args],
            timeout=self.timeout if timeout is None else timeout,
            cancel=cancel,
        )
