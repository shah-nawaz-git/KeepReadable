import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from scripts.create_demo_archive import create_demo_archive

pytestmark = pytest.mark.packaged

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "dist" / "KeepReadable"
CLI = DISTRIBUTION / "KeepReadable-cli.exe"
GUI = DISTRIBUTION / "KeepReadable.exe"


@pytest.mark.skipif(not CLI.is_file(), reason="Windows package has not been built")
def test_packaged_cli_and_desktop_smoke(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    archive = tmp_path / "demo-archive"
    create_demo_archive(archive, seed=42, media=False)
    environment = {
        **os.environ,
        "KEEPREADABLE_DATA_DIR": str(data_dir),
        "QT_QPA_PLATFORM": "windows",
    }

    tools = subprocess.run(
        [str(CLI), "tools"],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        shell=False,
        timeout=60,
    )
    assert tools.returncode == 0, tools.stderr
    assert "siegfried:" in tools.stdout.casefold()
    assert "ffmpeg:" in tools.stdout.casefold()

    added = subprocess.run(
        [str(CLI), "add", "Demo Archive", str(archive), "--data-dir", str(data_dir)],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        shell=False,
        timeout=60,
    )
    assert added.returncode == 0, added.stderr

    audited = subprocess.run(
        [
            str(CLI),
            "audit",
            str(archive),
            "--mode",
            "quick",
            "--json",
            "--data-dir",
            str(data_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        shell=False,
        timeout=180,
    )
    assert audited.returncode == 0, audited.stderr
    document = json.loads(audited.stdout)
    assert document["status"] == "completed"

    report_dir = tmp_path / "reports"
    reported = subprocess.run(
        [
            str(CLI),
            "report",
            str(document["run_id"]),
            "--out",
            str(report_dir),
            "--format",
            "html",
            "--data-dir",
            str(data_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        shell=False,
        timeout=120,
    )
    assert reported.returncode == 0, reported.stderr
    assert len(list(report_dir.glob("*.html"))) == 1

    licenses = DISTRIBUTION / "LICENSES"
    assert (DISTRIBUTION / "LICENSE.txt").is_file()
    assert (DISTRIBUTION / "THIRD_PARTY.md").is_file()
    assert (licenses / "INDEX.txt").is_file()
    qt_dirs = list(licenses.glob("Qt-PySide6-*"))
    assert qt_dirs
    assert (qt_dirs[0] / "LGPL-3.0-only.txt").is_file()
    assert (qt_dirs[0] / "GPL-3.0-only.txt").is_file()
    assert list(licenses.glob("pikepdf-*/third-party-licenses/qpdf.txt"))
    assert list(licenses.glob("Python-*/LICENSE.txt"))
    assert any(path.is_dir() and any(path.iterdir()) for path in licenses.glob("pillow-*"))
    assert any(path.is_dir() and any(path.iterdir()) for path in licenses.glob("reportlab-*"))
    assert not (DISTRIBUTION / "_internal" / "mypy").exists()
    executables = {path.name.casefold() for path in DISTRIBUTION.rglob("*.exe")}
    assert not {"sf.exe", "ffmpeg.exe", "ffprobe.exe"} & executables

    process = subprocess.Popen(
        [str(GUI)],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        shell=False,
    )
    try:
        time.sleep(6)
        assert process.poll() is None
        assert (data_dir / "keepreadable.db").is_file()
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
