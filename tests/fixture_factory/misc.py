import random
from pathlib import Path

from tests.fixture_factory.images import make_png


def make_unknown_binary(path: Path, seed: int = 1) -> Path:
    randomizer = random.Random(seed)
    path.write_bytes(bytes(randomizer.randrange(256) for _ in range(4096)))
    return path


def make_text(path: Path, text: str = "KeepReadable fixture\n") -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def make_png_named_jpg(path: Path, seed: int = 1) -> Path:
    return make_png(path, seed=seed)
