from pathlib import Path

import pytest
from PIL import Image

from keepreadable.integrations.ffmpeg import FFmpegAdapter, FFprobeError
from keepreadable.integrations.siegfried import SiegfriedAdapter
from keepreadable.integrations.tool_locator import ToolLocator, ToolName
from keepreadable.utilities.filesystem import extended_path

pytestmark = pytest.mark.external_tools


def test_real_siegfried_identifies_disguised_png(
    tmp_path: Path, tools_available: ToolLocator
) -> None:
    executable = tools_available.locate(ToolName.SIEGFRIED)
    home = tools_available.siegfried_home()
    assert executable is not None
    assert home is not None
    disguised = tmp_path / "image.jpg"
    Image.new("RGB", (2, 2), "red").save(disguised, format="PNG")

    result = SiegfriedAdapter(executable, home).identify([disguised])[str(disguised)]
    assert result.identified
    assert result.best_match is not None
    assert result.best_match.puid == "fmt/11"
    assert result.extension_mismatch


def test_real_siegfried_accepts_extended_long_path(
    tmp_path: Path, tools_available: ToolLocator
) -> None:
    executable = tools_available.locate(ToolName.SIEGFRIED)
    home = tools_available.siegfried_home()
    assert executable is not None
    assert home is not None
    directory = tmp_path
    while len(str(directory / "long.png")) <= 270:
        directory /= "long-segment-name-0123456789"
        Path(extended_path(directory)).mkdir()
    image_path = directory / "long.png"
    with open(extended_path(image_path), "wb") as stream:
        Image.new("RGB", (2, 2), "blue").save(stream, format="PNG")

    result = SiegfriedAdapter(executable, home).identify([image_path])[str(image_path)]
    assert result.identified
    assert result.best_match is not None
    assert result.best_match.puid == "fmt/11"


def test_real_ffmpeg_probe_decode_and_truncation(
    tmp_path: Path, tools_available: ToolLocator
) -> None:
    ffmpeg = tools_available.locate(ToolName.FFMPEG)
    ffprobe = tools_available.locate(ToolName.FFPROBE)
    assert ffmpeg is not None
    assert ffprobe is not None
    adapter = FFmpegAdapter(ffmpeg, ffprobe, timeout=60)
    output = tmp_path / "sample.mp4"
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
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(output),
        ]
    )
    assert generated.returncode == 0

    probe = adapter.probe(output)
    assert probe.video_streams
    assert probe.audio_streams
    assert adapter.decode_to_null(output).success

    truncated = tmp_path / "truncated.mp4"
    content = output.read_bytes()
    truncated.write_bytes(content[: int(len(content) * 0.6)])
    try:
        truncated_probe_failed = not adapter.probe(truncated).streams
    except FFprobeError:
        truncated_probe_failed = True
    assert truncated_probe_failed or not adapter.decode_to_null(truncated).success
