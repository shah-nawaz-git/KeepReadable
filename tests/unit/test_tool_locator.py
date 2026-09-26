from pathlib import Path
from typing import Any

from keepreadable.integrations.subprocess_runner import CommandResult
from keepreadable.integrations.tool_locator import ToolLocator, ToolName


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"tool")
    return path


def test_environment_override_wins(tmp_path: Path) -> None:
    override = touch(tmp_path / "override" / "sf.exe")
    installed = touch(tmp_path / "tools" / "siegfried" / "sf.exe")
    locator = ToolLocator(
        tmp_path / "tools",
        environ={"KEEPREADABLE_SF_PATH": str(override)},
        which=lambda _name: str(installed),
    )
    assert locator.locate(ToolName.SIEGFRIED) == override


def test_app_data_path_is_second(tmp_path: Path) -> None:
    installed = touch(tmp_path / "tools" / "ffmpeg" / "ffmpeg.exe")
    locator = ToolLocator(tmp_path / "tools", environ={}, which=lambda _name: None)
    assert locator.locate(ToolName.FFMPEG) == installed


def test_path_fallback_and_missing(tmp_path: Path) -> None:
    on_path = touch(tmp_path / "path" / "ffprobe.exe")
    locator = ToolLocator(
        tmp_path / "tools",
        environ={},
        which=lambda name: str(on_path) if name == "ffprobe.exe" else None,
    )
    assert locator.locate(ToolName.FFPROBE) == on_path
    assert locator.locate(ToolName.SIEGFRIED) is None


def test_siegfried_home_prefers_signature_next_to_executable(tmp_path: Path) -> None:
    executable = touch(tmp_path / "custom" / "sf.exe")
    executable.with_name("default.sig").write_bytes(b"signature")
    locator = ToolLocator(
        tmp_path / "tools",
        environ={"KEEPREADABLE_SF_PATH": str(executable)},
        which=lambda _name: None,
    )
    assert locator.siegfried_home() == executable.parent


def test_inventory_parses_versions(tmp_path: Path) -> None:
    sf = touch(tmp_path / "tools" / "siegfried" / "sf.exe")
    sf.with_name("default.sig").write_bytes(b"signature")
    touch(tmp_path / "tools" / "ffmpeg" / "ffmpeg.exe")
    touch(tmp_path / "tools" / "ffmpeg" / "ffprobe.exe")

    def runner(args: list[str], **_kwargs: Any) -> CommandResult:
        executable = Path(args[0]).name
        outputs = {
            "sf.exe": b"siegfried 1.11.8\ndefault.sig\n",
            "ffmpeg.exe": b"ffmpeg version 8.1.2-test\n",
            "ffprobe.exe": b"ffprobe version 8.1.2-test\n",
        }
        return CommandResult(tuple(args), 0, outputs[executable], b"", 0.1, False)

    inventory = ToolLocator(tmp_path / "tools", environ={}).inventory(runner)
    assert inventory[ToolName.SIEGFRIED].version == "1.11.8"
    assert inventory[ToolName.FFMPEG].version == "8.1.2-test"
    assert inventory[ToolName.FFPROBE].version == "8.1.2-test"
    assert all(status.installed for status in inventory.values())
