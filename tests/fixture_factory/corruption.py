import hashlib
import random
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def assert_unchanged(path: Path) -> Iterator[None]:
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    yield
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    assert after == before


def truncate_file(path: Path, keep_fraction: float) -> Path:
    if not 0 <= keep_fraction <= 1:
        raise ValueError("keep_fraction must be between 0 and 1")
    size = path.stat().st_size
    with path.open("r+b") as stream:
        stream.truncate(int(size * keep_fraction))
    return path


def flip_bytes(path: Path, offset: int, count: int, seed: int = 1) -> Path:
    randomizer = random.Random(seed)
    with path.open("r+b") as stream:
        stream.seek(offset)
        original = stream.read(count)
        stream.seek(offset)
        stream.write(bytes(value ^ randomizer.randrange(1, 256) for value in original))
    return path


def overwrite_bytes(path: Path, offset: int, data: bytes) -> Path:
    with path.open("r+b") as stream:
        stream.seek(offset)
        stream.write(data)
    return path


def zero_range(path: Path, offset: int, count: int) -> Path:
    return overwrite_bytes(path, offset, b"\0" * count)
