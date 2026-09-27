import hashlib
import json
import sys
import unicodedata
from pathlib import Path

import pytest

from keepreadable.analysis.discovery import DiscoveryOptions, discover_files
from keepreadable.analysis.hashing import hash_file
from keepreadable.analysis.normalization import normalize_relative_path
from keepreadable.integrations.ffmpeg import FFmpegAdapter
from keepreadable.integrations.siegfried import (
    SiegfriedAdapter,
    SiegfriedOutputError,
    parse_siegfried_json,
)
from keepreadable.integrations.subprocess_runner import CommandResult, run_command
from keepreadable.integrations.tool_locator import ToolLocator, ToolName
from keepreadable.utilities.filesystem import extended_path
from keepreadable.validators.base import ValidationDepth
from keepreadable.validators.zip_archive import ZipValidator
from tests.fixture_factory import make_jpeg, make_traversal_zip


@pytest.mark.parametrize(
    "name",
    [
        "evil && calc.exe.jpg",
        "$(rm -rf x).png",
        "%TEMP%.txt",
        "file;name.pdf",
        "name with 'quotes'.zip",
        "-not-an-option.mp4",
        "rtl-\u202egpj.txt",
        "zero-\u200djoin.txt",
        "emoji-🙂.txt",
    ],
)
def test_adversarial_filenames_are_literal_and_hashable(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"literal filename payload")
    discovered = list(discover_files(tmp_path, DiscoveryOptions()))
    assert [item.relative_path for item in discovered] == [name]
    assert hash_file(path).sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    result = run_command(
        [sys.executable, "-c", "import json,sys; print(json.dumps(sys.argv[1:]))", name],
        timeout=5,
    )
    assert json.loads(result.stdout) == [name]
    assert result.args[-1] == name


@pytest.mark.external_tools
def test_siegfried_receives_adversarial_filename_unchanged(tmp_path: Path) -> None:
    path = make_jpeg(tmp_path / "evil && calc.exe.jpg")
    locator = ToolLocator()
    executable = locator.locate(ToolName.SIEGFRIED)
    home = locator.siegfried_home()
    if executable is None or home is None:
        pytest.skip("Siegfried is unavailable")
    result = SiegfriedAdapter(executable, home).identify([path])
    assert str(path) in result
    assert result[str(path)].path == str(path)


def test_unicode_normalization_and_long_filename(tmp_path: Path) -> None:
    nfc = "Café-🙂.txt"
    nfd = unicodedata.normalize("NFD", nfc)
    (tmp_path / nfd).write_bytes(b"unicode")
    long_name = "x" * 235 + ".txt"
    with open(extended_path(tmp_path / long_name), "wb") as stream:
        stream.write(b"long")
    paths = {item.normalized_path for item in discover_files(tmp_path, DiscoveryOptions())}
    assert normalize_relative_path(nfc) in paths
    assert normalize_relative_path(long_name) in paths


def test_ffprobe_uses_literal_file_protocol_for_leading_dash(tmp_path: Path) -> None:
    path = tmp_path / "-not-an-option.mp4"
    path.write_bytes(b"media")

    def runner(args: list[str], **_kwargs: object) -> CommandResult:
        assert args[-2] == "-i"
        assert args[-1] == f"file:{path}"
        assert "-not-an-option.mp4" in args[-1]
        return CommandResult(tuple(args), 0, b'{"streams":[],"format":{}}', b"", 0.1, False)

    FFmpegAdapter(None, tmp_path / "ffprobe.exe", runner=runner).probe(path)


def test_zip_traversal_is_never_extracted(tmp_path: Path) -> None:
    archive = make_traversal_zip(tmp_path / "traversal.zip")
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    result = ZipValidator(100, 100_000_000, 100).validate(archive, depth=ValidationDepth.DEEP)
    after = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    assert before == after
    assert result.structural.value == "passed"
    assert result.details["unsafe_entry_names"]
    assert not (tmp_path.parent / "escape.txt").exists()


@pytest.mark.parametrize(
    "payload",
    [
        b'{"files":"nope"}',
        b'{"files":[',
        b"x" * (10 * 1024 * 1024),
    ],
    ids=("wrong-shape", "truncated", "garbage-10mb"),
)
def test_malformed_siegfried_output_is_rejected(payload: bytes) -> None:
    with pytest.raises(SiegfriedOutputError):
        parse_siegfried_json(payload)


def test_forbidden_user_facing_terminology_absent() -> None:
    project = Path(__file__).parents[2]
    source = project / "src" / "keepreadable"
    forbidden = (
        "corrupt",
        "guaranteed",
        "permanently",
        "future-proof",
        "100%",
        "archival master",
        "fully valid",
        "will become obsolete",
    )
    allowed_phrases = (
        (
            "KeepReadable is a Python desktop application that audits personal digital "
            "archives for corruption, unreadable files and format risks, then creates and "
            "verifies safe compatibility copies without modifying the originals."
        ),
        (
            "Built a Python digital-preservation engine that audits mixed personal archives "
            "for corruption and format/readability risks, creates verified compatibility "
            "copies, and tracks long-term file integrity."
        ),
        "width:100%",
    )
    paths = [
        path
        for path in source.rglob("*")
        if path.suffix.casefold() in {".py", ".yml", ".j2", ".qss"}
    ]
    paths.extend((project / "README.md", project / "AGENTS.md"))
    paths.extend((project / "docs").glob("*.md"))
    hits: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8").casefold()
        for phrase in allowed_phrases:
            text = text.replace(phrase.casefold(), "")
        for word in forbidden:
            if word in text:
                hits.append(f"{path.relative_to(project).as_posix()}: {word}")
    assert hits == []


def test_tracked_text_files_contain_no_local_profile_paths() -> None:
    project = Path(__file__).parents[2]
    suffixes = {".py", ".md", ".yml", ".yaml", ".json", ".j2", ".qss", ".toml", ".txt", ".spec"}
    markers = ("c:\\users\\", "c:/users/", "/users/hp", "/home/")
    hits: list[str] = []
    for folder in ("src", "tests", "docs", "scripts", "packaging", ".github"):
        for path in (project / folder).rglob("*"):
            if path.suffix.casefold() not in suffixes or ".tmp" in path.parts:
                continue
            if path == Path(__file__):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").casefold()
            hits.extend(
                f"{path.relative_to(project).as_posix()}: {m}" for m in markers if m in text
            )
    assert hits == []
