import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from keepreadable import __version__  # noqa: E402

README_TEXT = f"""KeepReadable {__version__} for Windows

INSTALLATION
1. Unzip the complete archive to a folder you can write to.
2. Run KeepReadable.exe for the desktop application.
3. KeepReadable stores local application data in %LOCALAPPDATA%\\KeepReadable by default.

COMMAND LINE
KeepReadable-cli.exe provides the headless command-line interface. Run
KeepReadable-cli.exe --help from Command Prompt or PowerShell for commands.

EXTERNAL TOOLS
Third-party tools are not bundled in this distribution to keep the download smaller and
to keep their licences and provenance clear. Install the pinned, checksum-verified tools
on demand from Settings > Install missing tools in the desktop application.

WINDOWS SMARTSCREEN
This build is unsigned. Microsoft Defender SmartScreen may show a warning. Review the
publisher information and file source before choosing to run an unsigned executable.
"""


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def build() -> tuple[Path, int, int, float]:
    if sys.platform != "win32":
        raise RuntimeError("The Windows package must be built on Windows")
    started = time.monotonic()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            str(ROOT / "packaging" / "keepreadable.spec"),
        ],
        cwd=ROOT,
        check=True,
        shell=False,
        timeout=1800,
    )
    distribution = ROOT / "dist" / "KeepReadable"
    if not (distribution / "KeepReadable.exe").is_file():
        raise RuntimeError("KeepReadable.exe was not created")
    if not (distribution / "KeepReadable-cli.exe").is_file():
        raise RuntimeError("KeepReadable-cli.exe was not created")
    (distribution / "README-INSTALL.txt").write_text(
        README_TEXT,
        encoding="utf-8",
    )
    archive = ROOT / "dist" / f"KeepReadable-{__version__}-windows-x64.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(
        archive,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as package:
        for item in sorted(distribution.rglob("*")):
            if item.is_file():
                package.write(item, item.relative_to(distribution).as_posix())
    elapsed = time.monotonic() - started
    folder_bytes = directory_size(distribution)
    zip_bytes = archive.stat().st_size
    print(f"Built {distribution}")
    print(f"Folder size: {folder_bytes} bytes")
    print(f"ZIP: {archive} ({zip_bytes} bytes)")
    print(f"Build time: {elapsed:.2f} seconds")
    return archive, folder_bytes, zip_bytes, elapsed


def main() -> int:
    build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
