import os
from datetime import UTC, datetime
from pathlib import Path

from keepreadable.utilities.clock import utcnow
from keepreadable.utilities.filesystem import extended_path, filesystem_identity


def test_utcnow_returns_naive_utc() -> None:
    before = datetime.now(UTC).replace(tzinfo=None)
    value = utcnow()
    after = datetime.now(UTC).replace(tzinfo=None)
    assert value.tzinfo is None
    assert before <= value <= after


def test_filesystem_identity_uses_device_and_inode(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_bytes(b"content")
    result = path.stat()
    expected = f"{result.st_dev}:{result.st_ino}" if result.st_dev and result.st_ino else None
    assert filesystem_identity(result) == expected


def test_extended_path_behavior() -> None:
    short = Path("short.txt")
    assert extended_path(short) == str(short)
    long_path = Path("C:/" + "x" * 260)
    if os.name == "nt":
        assert extended_path(long_path).startswith("\\\\?\\")
    else:
        assert extended_path(long_path) == str(long_path)
