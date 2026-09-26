import json
from pathlib import Path
from typing import Any

import pytest

from keepreadable.integrations.siegfried import (
    SiegfriedAdapter,
    SiegfriedError,
    SiegfriedOutputError,
    parse_siegfried_json,
    parse_version_output,
)
from keepreadable.integrations.subprocess_runner import CommandResult, ToolNotFoundError

FIXTURE = Path(__file__).parents[1] / "fixtures" / "siegfried_sample.json"


def command_result(
    args: list[str],
    *,
    returncode: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
    timed_out: bool = False,
) -> CommandResult:
    return CommandResult(tuple(args), returncode, stdout, stderr, 0.1, timed_out)


def test_parse_real_sample_and_match_properties() -> None:
    info, results = parse_siegfried_json(FIXTURE.read_bytes())
    assert info.version == "1.11.8"
    assert info.signature_file == "default.sig"
    assert info.signature_created == "2026-09-15T19:45:35+10:00"
    assert info.identifiers.startswith("DROID_SignatureFile_V125.xml")
    disguised, unknown, missing = results
    assert disguised.identified
    assert disguised.best_match is not None
    assert disguised.best_match.puid == "fmt/11"
    assert disguised.extension_mismatch
    assert not disguised.extension_only
    assert not unknown.identified
    assert unknown.warnings == ("no match",)
    assert missing.error is not None
    assert not missing.identified


def test_extension_only_property() -> None:
    payload = (
        b'{"files":[{"filename":"x","matches":['
        b'{"ns":"pronom","id":"fmt/1","warning":"match on extension only"}]}]}'
    )
    _, results = parse_siegfried_json(payload)
    assert results[0].extension_only


def test_malformed_json_and_wrong_shape_raise() -> None:
    with pytest.raises(SiegfriedOutputError):
        parse_siegfried_json(b"not json")
    with pytest.raises(SiegfriedOutputError):
        parse_siegfried_json(b"[]")


def test_missing_keys_are_tolerated() -> None:
    info, results = parse_siegfried_json(b"{}")
    assert info.version == ""
    assert info.signature_file == ""
    assert results == []


def test_adapter_writes_utf8_lf_list_and_expected_arguments(tmp_path: Path) -> None:
    paths = [tmp_path / "space name.txt", tmp_path / "ünïcode 文件.txt"]

    def runner(args: list[str], **kwargs: Any) -> CommandResult:
        assert "-json" in args
        assert "-home" in args
        assert "-f" in args
        assert kwargs["timeout"] == 123
        list_path = Path(args[args.index("-f") + 1])
        raw = list_path.read_bytes()
        assert b"\r\n" not in raw
        sent = raw.decode("utf-8").splitlines()
        assert sent == [str(path) for path in paths]
        payload = {
            "siegfried": "1.11.8",
            "files": [
                {"filename": path, "filesize": 1, "errors": "", "matches": []} for path in sent
            ],
        }
        return command_result(args, stdout=json.dumps(payload).encode())

    adapter = SiegfriedAdapter(tmp_path / "sf.exe", tmp_path, runner=runner, timeout=123, multi=4)
    results = adapter.identify(paths)
    assert list(results) == [str(path) for path in paths]
    assert all(result.error is None for result in results.values())


def test_absent_report_gets_explicit_error(tmp_path: Path) -> None:
    def runner(args: list[str], **_kwargs: Any) -> CommandResult:
        return command_result(args, stdout=b'{"files":[]}')

    path = tmp_path / "not-reported.txt"
    result = SiegfriedAdapter(tmp_path / "sf.exe", tmp_path, runner=runner).identify([path])
    assert result[str(path)].error == "not reported by siegfried"


def test_timeout_raises(tmp_path: Path) -> None:
    def runner(args: list[str], **_kwargs: Any) -> CommandResult:
        return command_result(args, timed_out=True)

    with pytest.raises(SiegfriedError, match="timed out"):
        SiegfriedAdapter(tmp_path / "sf.exe", tmp_path, runner=runner).identify(
            [tmp_path / "file.txt"]
        )


def test_missing_tool_error_propagates(tmp_path: Path) -> None:
    def runner(_args: list[str], **_kwargs: Any) -> CommandResult:
        raise ToolNotFoundError("missing")

    with pytest.raises(ToolNotFoundError):
        SiegfriedAdapter(tmp_path / "sf.exe", tmp_path, runner=runner).identify(
            [tmp_path / "file.txt"]
        )


def test_version_parsing_and_adapter_info(tmp_path: Path) -> None:
    output = (
        "siegfried 1.11.8\n"
        "C:\\tools\\default.sig (2026-09-15T19:45:35+10:00)\n"
        "identifiers:\n"
        "  - pronom: DROID_SignatureFile_V125.xml; container-signature-20260119.xml\n"
    )
    parsed = parse_version_output(output)
    assert parsed.version == "1.11.8"
    assert parsed.signature_file == "default.sig"
    assert parsed.identifiers.endswith("container-signature-20260119.xml")

    def runner(args: list[str], **_kwargs: Any) -> CommandResult:
        return command_result(args, stdout=output.encode())

    assert SiegfriedAdapter(tmp_path / "sf.exe", tmp_path, runner=runner).info() == parsed
