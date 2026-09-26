import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from keepreadable.utilities.cancellation import CancellationToken
from keepreadable.utilities.filesystem import extended_path


@dataclass(frozen=True, slots=True)
class HashResult:
    sha256: str
    bytes_read: int
    size_before: int
    mtime_ns_before: int
    size_after: int
    mtime_ns_after: int

    @property
    def changed_during_read(self) -> bool:
        return self.size_before != self.size_after or self.mtime_ns_before != self.mtime_ns_after


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(
    path: Path,
    *,
    buffer_size: int = 1 << 20,
    cancel: CancellationToken | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> HashResult:
    if buffer_size <= 0:
        raise ValueError("buffer_size must be positive")
    path_value = extended_path(path)
    before = os.stat(path_value)
    digest = hashlib.sha256()
    bytes_read = 0
    with open(path_value, "rb", buffering=0) as stream:
        while True:
            if cancel is not None:
                cancel.raise_if_cancelled()
            chunk = stream.read(buffer_size)
            if not chunk:
                break
            digest.update(chunk)
            bytes_read += len(chunk)
            if on_progress is not None:
                on_progress(bytes_read)
    after = os.stat(path_value)
    return HashResult(
        sha256=digest.hexdigest(),
        bytes_read=bytes_read,
        size_before=before.st_size,
        mtime_ns_before=before.st_mtime_ns,
        size_after=after.st_size,
        mtime_ns_after=after.st_mtime_ns,
    )
