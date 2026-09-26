import unicodedata
from pathlib import Path


def normalize_relative_path(rel: str) -> str:
    normalized = rel.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    return unicodedata.normalize("NFC", normalized).casefold()


def relative_path_for_storage(root: Path, path: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return unicodedata.normalize("NFC", relative)


def extension_of(relative_path: str) -> str:
    name = relative_path.replace("\\", "/").rsplit("/", 1)[-1]
    suffix = Path(name).suffix
    return suffix[1:].lower() if suffix else ""
