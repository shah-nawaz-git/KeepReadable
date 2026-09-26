import os
import re
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from platformdirs import user_data_dir

from keepreadable.config.paths import tools_dir as default_tools_dir
from keepreadable.integrations.subprocess_runner import Runner, run_command


class ToolName(StrEnum):
    SIEGFRIED = "siegfried"
    FFMPEG = "ffmpeg"
    FFPROBE = "ffprobe"


@dataclass(frozen=True, slots=True)
class ToolStatus:
    name: ToolName
    installed: bool
    path: Path | None
    version: str | None
    detail: str | None
    source: str | None


_ENVIRONMENT_NAMES = {
    ToolName.SIEGFRIED: "KEEPREADABLE_SF_PATH",
    ToolName.FFMPEG: "KEEPREADABLE_FFMPEG_PATH",
    ToolName.FFPROBE: "KEEPREADABLE_FFPROBE_PATH",
}
_EXECUTABLE_NAMES = {
    ToolName.SIEGFRIED: "sf.exe" if os.name == "nt" else "sf",
    ToolName.FFMPEG: "ffmpeg.exe" if os.name == "nt" else "ffmpeg",
    ToolName.FFPROBE: "ffprobe.exe" if os.name == "nt" else "ffprobe",
}
_TOOL_DIRECTORIES = {
    ToolName.SIEGFRIED: "siegfried",
    ToolName.FFMPEG: "ffmpeg",
    ToolName.FFPROBE: "ffmpeg",
}


class ToolLocator:
    def __init__(
        self,
        tools_dir: Path | None = None,
        environ: Mapping[str, str] | None = None,
        which: Callable[[str], str | None] = shutil.which,
        default_user_tools_dir: Path | None = None,
    ) -> None:
        self.tools_dir = tools_dir or default_tools_dir()
        self.default_user_tools_dir = default_user_tools_dir or (
            Path(user_data_dir("KeepReadable", appauthor=False)) / "tools"
        )
        self.environ = environ if environ is not None else os.environ
        self.which = which

    def _frozen_candidate(self, name: ToolName) -> Path | None:
        if not getattr(sys, "frozen", False):
            return None
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return bundle_root / "tools" / _TOOL_DIRECTORIES[name] / _EXECUTABLE_NAMES[name]

    def _locate_with_source(self, name: ToolName) -> tuple[Path | None, str | None]:
        override = self.environ.get(_ENVIRONMENT_NAMES[name])
        candidates = [
            (Path(override), "env") if override else (None, None),
            (
                self.tools_dir / _TOOL_DIRECTORIES[name] / _EXECUTABLE_NAMES[name],
                "app_data",
            ),
            (
                self.default_user_tools_dir / _TOOL_DIRECTORIES[name] / _EXECUTABLE_NAMES[name],
                "app_data",
            ),
            (self._frozen_candidate(name), "bundled"),
        ]
        for candidate, source in candidates:
            if candidate is not None and candidate.is_file():
                return candidate, source
        located = self.which(_EXECUTABLE_NAMES[name])
        return (Path(located), "path") if located else (None, None)

    def locate(self, name: ToolName) -> Path | None:
        return self._locate_with_source(name)[0]

    def siegfried_home(self) -> Path | None:
        executable = self.locate(ToolName.SIEGFRIED)
        if executable is not None and (executable.parent / "default.sig").is_file():
            return executable.parent
        installed_home = self.tools_dir / "siegfried"
        return installed_home if (installed_home / "default.sig").is_file() else None

    def inventory(self, runner: Runner = run_command) -> dict[ToolName, ToolStatus]:
        return {name: self._status(name, runner) for name in ToolName}

    def _status(self, name: ToolName, runner: Runner) -> ToolStatus:
        executable, source = self._locate_with_source(name)
        if executable is None:
            return ToolStatus(name, False, None, None, "not found", None)
        args = [str(executable), "-version"]
        if name is ToolName.SIEGFRIED:
            home = self.siegfried_home()
            if home is not None:
                args.extend(["-home", str(home)])
        try:
            result = runner(args, timeout=15)
        except Exception as exc:
            return ToolStatus(name, False, executable, None, str(exc), source)
        output = result.stdout.decode("utf-8", errors="replace").strip()
        if result.timed_out or result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip() or output
            return ToolStatus(
                name, False, executable, None, detail or "version check failed", source
            )
        version = _version_from_output(name, output)
        return ToolStatus(name, version is not None, executable, version, output or None, source)


def _version_from_output(name: ToolName, output: str) -> str | None:
    first_line = output.splitlines()[0] if output else ""
    if name is ToolName.SIEGFRIED:
        match = re.search(r"\bsiegfried\s+([^\s]+)", first_line, re.IGNORECASE)
    else:
        match = re.search(r"\bff(?:mpeg|probe)\s+version\s+([^\s]+)", first_line, re.IGNORECASE)
    return match.group(1) if match else None
