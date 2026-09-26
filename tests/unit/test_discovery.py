from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

import pytest

from keepreadable.analysis.discovery import DiscoveryOptions, SkippedItem, discover_files
from keepreadable.utilities.cancellation import CancellationToken, OperationCancelled
from keepreadable.utilities.filesystem import SkipReason, extended_path


def test_discovery_is_lazy_deterministic_and_handles_names(tmp_path: Path) -> None:
    nested = tmp_path / "a folder" / "nested"
    nested.mkdir(parents=True)
    (nested / "b.txt").write_bytes(b"b")
    (nested / "a.txt").write_bytes(b"a")
    (tmp_path / "zero bytes.bin").write_bytes(b"")
    (tmp_path / "ünïcode 文件 🙂.txt").write_text("content", encoding="utf-8")
    (tmp_path / "z.txt").write_bytes(b"z")

    first = list(discover_files(tmp_path, DiscoveryOptions()))
    second = list(discover_files(tmp_path, DiscoveryOptions()))

    assert first == second
    paths = [item.relative_path for item in first]
    assert paths == sorted(paths, key=str.casefold)
    assert "ünïcode 文件 🙂.txt" in paths
    zero = next(item for item in first if item.relative_path == "zero bytes.bin")
    assert zero.size == 0
    assert zero.normalized_path == "zero bytes.bin"


def test_permission_error_skips_directory_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "hidden.txt").write_bytes(b"hidden")
    (tmp_path / "visible.txt").write_bytes(b"visible")
    real_scandir = os.scandir

    def guarded_scandir(path: str) -> os.ScandirIterator[str]:
        if os.path.normcase(path) == os.path.normcase(str(blocked)):
            raise PermissionError("blocked for test")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", guarded_scandir)
    skipped: list[SkippedItem] = []
    files = list(discover_files(tmp_path, DiscoveryOptions(), on_skip=skipped.append))

    assert [item.relative_path for item in files] == ["visible.txt"]
    assert [(item.relative_path, item.reason) for item in skipped] == [
        ("blocked", SkipReason.PERMISSION_DENIED)
    ]


def test_vanished_entry_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_scandir = os.scandir

    class VanishedEntry:
        name = "vanished.txt"

        def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
            raise FileNotFoundError("vanished for test")

    class FakeScandir:
        def __enter__(self) -> FakeScandir:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def __iter__(self) -> Any:
            return iter([VanishedEntry()])

    def fake_scandir(path: str) -> os.ScandirIterator[str] | FakeScandir:
        if os.path.normcase(path) == os.path.normcase(str(tmp_path)):
            return FakeScandir()
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", fake_scandir)
    skipped: list[SkippedItem] = []
    assert list(discover_files(tmp_path, DiscoveryOptions(), on_skip=skipped.append)) == []
    assert len(skipped) == 1
    assert skipped[0].relative_path == "vanished.txt"
    assert skipped[0].reason is SkipReason.VANISHED


def test_symlink_is_not_followed(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "file.txt").write_bytes(b"content")
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    skipped: list[SkippedItem] = []
    files = list(discover_files(tmp_path, DiscoveryOptions(), on_skip=skipped.append))
    assert [item.relative_path for item in files] == ["target/file.txt"]
    assert any(
        item.relative_path == "link" and item.reason is SkipReason.REPARSE_POINT for item in skipped
    )


def test_followed_symlink_loop_does_not_recurse(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "file.txt").write_bytes(b"content")
    loop = target / "loop"
    try:
        loop.symlink_to(tmp_path, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    skipped: list[SkippedItem] = []
    files = list(
        discover_files(
            tmp_path,
            DiscoveryOptions(follow_reparse_points=True),
            on_skip=skipped.append,
        )
    )
    assert [item.relative_path for item in files] == ["target/file.txt"]
    assert any(item.relative_path == "target/loop" for item in skipped)


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-specific")
def test_junction_is_not_followed(tmp_path: Path) -> None:
    try:
        create_junction = importlib.import_module("_winapi").CreateJunction
    except (ImportError, AttributeError):
        pytest.skip("_winapi.CreateJunction is unavailable")
    target = tmp_path / "target"
    target.mkdir()
    (target / "file.txt").write_bytes(b"content")
    junction = tmp_path / "junction"
    try:
        create_junction(str(target), str(junction))
    except OSError as exc:
        pytest.skip(f"junction creation unavailable: {exc}")

    skipped: list[SkippedItem] = []
    files = list(discover_files(tmp_path, DiscoveryOptions(), on_skip=skipped.append))
    assert [item.relative_path for item in files] == ["target/file.txt"]
    assert any(
        item.relative_path == "junction" and item.reason is SkipReason.REPARSE_POINT
        for item in skipped
    )


def test_long_path_is_discovered(tmp_path: Path) -> None:
    deep = tmp_path
    try:
        while len(str(deep / "file.txt")) <= 270:
            deep = deep / ("segment" * 8)
            os.mkdir(extended_path(deep))
        file_path = deep / "file.txt"
        with open(extended_path(file_path), "wb") as stream:
            stream.write(b"long")
    except OSError as exc:
        pytest.skip(f"long paths unavailable: {exc}")

    files = list(discover_files(tmp_path, DiscoveryOptions()))
    assert len(files) == 1
    assert files[0].relative_path.endswith("file.txt")
    assert files[0].size == 4


def test_cancellation_is_checked_during_large_directory(tmp_path: Path) -> None:
    for index in range(300):
        (tmp_path / f"{index:03}.txt").write_bytes(b"x")
    token = CancellationToken()
    iterator = discover_files(tmp_path, DiscoveryOptions(), cancel=token)
    assert next(iterator).relative_path == "000.txt"
    token.cancel()
    with pytest.raises(OperationCancelled):
        list(iterator)


def test_data_directory_is_excluded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app_data = tmp_path / "app-data"
    app_data.mkdir()
    (app_data / "database.db").write_bytes(b"data")
    (tmp_path / "original.txt").write_bytes(b"original")
    monkeypatch.setenv("KEEPREADABLE_DATA_DIR", str(app_data))

    files = list(discover_files(tmp_path, DiscoveryOptions()))
    assert [item.relative_path for item in files] == ["original.txt"]


def test_nonexistent_root_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        list(discover_files(tmp_path / "missing", DiscoveryOptions()))
