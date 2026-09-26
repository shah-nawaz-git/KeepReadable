import json
from pathlib import Path

import pytest

from keepreadable.cli import main
from tests.fixture_factory import make_jpeg


def test_cli_audit_json_and_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "archive"
    root.mkdir()
    make_jpeg(root / "image.jpg")
    data = tmp_path / "data"
    code = main(
        [
            "audit",
            str(root),
            "--mode",
            "quick",
            "--json",
            "--data-dir",
            str(data),
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    document = json.loads(output)
    assert document["status"] == "completed"
    assert document["counts"]["files"] == 1
    assert len(document["files"]) == 1
    reports = tmp_path / "reports"
    report_code = main(
        [
            "report",
            str(document["run_id"]),
            "--out",
            str(reports),
            "--format",
            "both",
            "--data-dir",
            str(data),
        ]
    )
    assert report_code == 0
    assert len(list(reports.glob("*.html"))) == 1
    assert len(list(reports.glob("*.pdf"))) == 1
