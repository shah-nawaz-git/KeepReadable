import math
import struct
import wave
from pathlib import Path

from keepreadable.integrations.ffmpeg import FFmpegAdapter
from keepreadable.integrations.tool_locator import ToolLocator, ToolName


def _adapter() -> FFmpegAdapter | None:
    locator = ToolLocator()
    ffmpeg = locator.locate(ToolName.FFMPEG)
    ffprobe = locator.locate(ToolName.FFPROBE)
    return FFmpegAdapter(ffmpeg, ffprobe, timeout=60) if ffmpeg and ffprobe else None


def ffmpeg_available() -> bool:
    return _adapter() is not None


def _run(path: Path, arguments: list[str]) -> Path:
    adapter = _adapter()
    if adapter is None:
        raise RuntimeError("FFmpeg is unavailable")
    result = adapter.run(["-y", *arguments, str(path)], timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    return path


def _video(
    path: Path, seconds: float, with_audio: bool, video_codec: str, audio_codec: str
) -> Path:
    arguments = [
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={seconds}:size=64x64:rate=10",
    ]
    if with_audio:
        arguments.extend(["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"])
    arguments.extend(["-c:v", video_codec])
    if video_codec == "libx264":
        arguments.extend(["-pix_fmt", "yuv420p"])
    if with_audio:
        arguments.extend(["-c:a", audio_codec])
    return _run(path, arguments)


def make_mp4(path: Path, seconds: float = 1, with_audio: bool = True) -> Path:
    return _video(path, seconds, with_audio, "libx264", "aac")


def make_mov(path: Path, seconds: float = 1, with_audio: bool = True) -> Path:
    return _video(path, seconds, with_audio, "libx264", "aac")


def make_avi(path: Path, seconds: float = 1, with_audio: bool = True) -> Path:
    return _video(path, seconds, with_audio, "mpeg4", "libmp3lame")


def _audio(path: Path, seconds: float, codec: str) -> Path:
    return _run(
        path,
        ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", codec],
    )


def make_mp3(path: Path, seconds: float = 1) -> Path:
    return _audio(path, seconds, "libmp3lame")


def make_wav(path: Path, seconds: float = 1) -> Path:
    return _audio(path, seconds, "pcm_s16le")


def make_flac(path: Path, seconds: float = 1) -> Path:
    return _audio(path, seconds, "flac")


def make_wav_stdlib(path: Path, seconds: float = 1) -> Path:
    sample_rate = 8000
    frame_count = int(sample_rate * seconds)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        frames = b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / sample_rate)))
            for i in range(frame_count)
        )
        output.writeframes(frames)
    return path
