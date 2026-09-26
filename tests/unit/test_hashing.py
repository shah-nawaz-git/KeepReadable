from __future__ import annotations

import builtins
import hashlib
import os
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

import pytest

from keepreadable.analysis.hashing import hash_file, sha256_hex
from keepreadable.utilities.cancellation import CancellationToken, OperationCancelled


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
        (b"abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
    ],
)
def test_known_digests(tmp_path: Path, data: bytes, expected: str) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(data)
    result = hash_file(path)
    assert result.sha256 == expected
    assert result.bytes_read == len(data)
    assert not result.changed_during_read
    assert sha256_hex(data) == expected


def test_large_file_matches_hashlib(tmp_path: Path) -> None:
    data = bytes(range(256)) * (3 * 1024 * 1024 // 256)
    path = tmp_path / "large.bin"
    path.write_bytes(data)
    result = hash_file(path, buffer_size=64 * 1024)
    assert result.sha256 == hashlib.sha256(data).hexdigest()
    assert result.bytes_read == 3 * 1024 * 1024


def test_hashing_always_reads_bounded_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(b"x" * 1000)
    real_open = builtins.open
    sizes: list[int] = []

    class RecordingStream:
        def __init__(self, stream: BinaryIO) -> None:
            self.stream = stream

        def __enter__(self) -> RecordingStream:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            self.stream.close()

        def read(self, size: int = -1) -> bytes:
            assert size >= 0
            sizes.append(size)
            return self.stream.read(size)

    def recording_open(*args: object, **kwargs: object) -> RecordingStream:
        return RecordingStream(real_open(*args, **kwargs))

    monkeypatch.setattr(builtins, "open", recording_open)
    hash_file(path, buffer_size=128)
    assert sizes
    assert max(sizes) == 128


def test_cancellation_after_first_chunk(tmp_path: Path) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(b"x" * 1024)
    token = CancellationToken()

    def cancel_after_chunk(_bytes_read: int) -> None:
        token.cancel()

    with pytest.raises(OperationCancelled):
        hash_file(path, buffer_size=128, cancel=token, on_progress=cancel_after_chunk)


def test_file_modified_during_hash_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(b"x" * 1024)
    appended = False

    def append_after_chunk(_bytes_read: int) -> None:
        nonlocal appended
        if not appended:
            with path.open("ab") as stream:
                stream.write(b"changed")
            appended = True

    result = hash_file(path, buffer_size=128, on_progress=append_after_chunk)
    assert result.changed_during_read
    assert result.size_after > result.size_before


def test_missing_file_error_is_propagated(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        hash_file(tmp_path / "missing.bin")


@pytest.mark.skipif(os.name != "nt", reason="Windows byte-range locking test")
def test_locked_file_error_is_propagated(tmp_path: Path) -> None:
    msvcrt = pytest.importorskip("msvcrt")
    path = tmp_path / "locked.bin"
    path.write_bytes(b"locked")
    with path.open("r+b") as locked:
        try:
            msvcrt.locking(locked.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            pytest.skip(f"file locking unavailable: {exc}")
        try:
            with pytest.raises(OSError):
                hash_file(path)
        finally:
            locked.seek(0)
            msvcrt.locking(locked.fileno(), msvcrt.LK_UNLCK, 1)
