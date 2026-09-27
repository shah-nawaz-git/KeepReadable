import platform
import re
import shutil
import subprocess
import sys
import time
import zipfile
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement

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

LICENSING
KeepReadable is released under the MIT License (LICENSE.txt). Bundled third-party
components and their licences are listed in THIRD_PARTY.md and the LICENSES folder.
Siegfried and FFmpeg are not included in this distribution; they are downloaded
separately under their own licences.
"""

QT_NOTICE = """PySide6, shiboken6 and the Qt 6 libraries located in _internal/PySide6 and
_internal/shiboken6 are used under the terms of the GNU Lesser General Public
License version 3 (LGPL-3.0-only). They are distributed as dynamically linked
shared libraries and may be replaced with interface-compatible builds. The full
LGPL-3.0 and GPL-3.0 texts are included in this directory as LGPL-3.0-only.txt
and GPL-3.0-only.txt.

Qt third-party attributions: https://doc.qt.io/qt-6/licenses-used-in-qt.html
Qt licensing information: https://www.qt.io/licensing
Qt for Python source code: https://code.qt.io/cgit/pyside/pyside-setup.git/
"""

LICENSE_NAME_PREFIXES = ("license", "licence", "copying", "notice", "authors")
NO_LICENSE_ALLOWED = frozenset(
    {
        "keepreadable",  # own code; MIT text ships as LICENSE.txt at the root
        "pikepdf.libs",  # wheel bundle dir; covered by the pikepdf dist entry
        "pyside6",  # covered by the Qt-PySide6 entry (LGPL-3.0/GPL-3.0 texts)
        "shiboken6",  # covered by the Qt-PySide6 entry (LGPL-3.0/GPL-3.0 texts)
    }
)


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def _runtime_dependencies() -> set[str]:
    """Installed distributions that keepreadable requires, transitively."""
    names: set[str] = set()
    pending = ["keepreadable"]
    while pending:
        dist = metadata.distribution(pending.pop())
        for requirement in dist.requires or []:
            parsed = Requirement(requirement)
            if parsed.marker is not None and not parsed.marker.evaluate():
                continue
            if _canonical(parsed.name) not in names:
                names.add(_canonical(parsed.name))
                pending.append(parsed.name)
    return names


def _package_candidates(entry_name: str) -> list[str]:
    name = entry_name
    for suffix in (".dist-info", ".egg-info", ".libs"):
        if name.casefold().endswith(suffix):
            name = name[: -len(suffix)]
            break
    name = re.sub(r"-\d[^/]*$", "", name)
    return [entry_name, name, name.replace("-", "_"), name.replace("_", "-")]


def _license_files(dist: metadata.Distribution) -> list[metadata.PackagePath]:
    entries: list[metadata.PackagePath] = []
    for file in dist.files or []:
        parts = file.parts
        marker = next(
            (
                index
                for index, part in enumerate(parts)
                if part.endswith((".dist-info", ".egg-info"))
            ),
            None,
        )
        if marker is None or marker + 1 >= len(parts):
            continue
        relative = parts[marker + 1 :]
        if relative[0].casefold() == "licenses" or relative[-1].casefold().startswith(
            LICENSE_NAME_PREFIXES
        ):
            entries.append(file)
    return entries


def _copy_dist_licenses(dist: metadata.Distribution, licenses_dir: Path) -> int:
    name = dist.metadata["Name"]
    target_root = licenses_dir / f"{name}-{dist.version}"
    copied = 0
    for file in _license_files(dist):
        parts = file.parts
        marker = next(
            index for index, part in enumerate(parts) if part.endswith((".dist-info", ".egg-info"))
        )
        relative = list(parts[marker + 1 :])
        if relative[0].casefold() == "licenses":
            relative = relative[1:]
        source = Path(dist.locate_file(file))
        if not source.is_file():
            continue
        destination = target_root.joinpath(*relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
    return copied


def _license_label(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    label = meta.get("License-Expression") or meta.get("License")
    if not label:
        classifiers = [
            value for value in meta.get_all("Classifier") or [] if value.startswith("License")
        ]
        label = "; ".join(classifiers) if classifiers else "see bundled license files"
    return str(label)


def write_license_notices(distribution: Path) -> None:
    licenses_dir = distribution / "LICENSES"
    licenses_dir.mkdir(exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", distribution / "LICENSE.txt")
    shutil.copy2(ROOT / "docs" / "THIRD_PARTY.md", distribution / "THIRD_PARTY.md")

    copied: dict[str, int] = {}
    index: dict[str, str] = {}

    def collect(name: str) -> int:
        key = _canonical(name)
        if key in copied:
            return copied[key]
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            copied[key] = 0
            return 0
        count = _copy_dist_licenses(dist, licenses_dir)
        copied[key] = count
        index[key] = f"{dist.metadata['Name']} {dist.version} | {_license_label(dist)}"
        return count

    packages = metadata.packages_distributions()
    internal = distribution / "_internal"
    problems: list[str] = []
    for entry in sorted(internal.iterdir()):
        if not (entry.is_dir() or entry.suffix.casefold() == ".pyd"):
            continue
        mapped = {
            _canonical(name)
            for candidate in _package_candidates(entry.name)
            for name in packages.get(candidate, [])
        }
        if not mapped:
            if entry.is_dir() and entry.name.casefold() not in NO_LICENSE_ALLOWED:
                problems.append(entry.name)
            continue
        if (
            entry.is_dir()
            and entry.name.casefold() not in NO_LICENSE_ALLOWED
            and not any(collect(name) for name in mapped)
        ):
            problems.append(entry.name)

    for name in _runtime_dependencies():
        collect(name)

    pyside_version = metadata.version("PySide6")
    qt_dir = licenses_dir / f"Qt-PySide6-{pyside_version}"
    qt_dir.mkdir(parents=True, exist_ok=True)
    for text_name in ("LGPL-3.0-only.txt", "GPL-3.0-only.txt"):
        shutil.copy2(ROOT / "packaging" / "licenses" / text_name, qt_dir / text_name)
    (qt_dir / "NOTICE.txt").write_text(QT_NOTICE, encoding="utf-8")
    index["qt-pyside6"] = (
        f"Qt/PySide6 {pyside_version} | LGPL-3.0-only (shared libraries; see NOTICE.txt)"
    )

    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError(f"Python license text not found: {python_license}")
    python_dir = licenses_dir / f"Python-{platform.python_version()}"
    python_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(python_license, python_dir / "LICENSE.txt")
    index["python"] = f"Python {platform.python_version()} | PSF-2.0"

    if problems:
        raise RuntimeError("Bundled components without license files: " + ", ".join(problems))
    lines = sorted(index.values(), key=str.casefold)
    (licenses_dir / "INDEX.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    write_license_notices(distribution)
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
