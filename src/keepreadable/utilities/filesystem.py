import os
import stat
from enum import StrEnum, auto
from pathlib import Path
from typing import Protocol


class SkipReason(StrEnum):
    REPARSE_POINT = auto()
    PERMISSION_DENIED = auto()
    VANISHED = auto()
    NOT_A_REGULAR_FILE = auto()
    PATH_TOO_LONG = auto()
    OS_ERROR = auto()


class _DirectoryEntry(Protocol):
    def is_symlink(self) -> bool: ...

    def stat(self, *, follow_symlinks: bool = True) -> os.stat_result: ...


def extended_path(path: Path) -> str:
    value = str(path)
    if os.name != "nt" or len(value) < 248 or value.startswith("\\\\?\\"):
        return value
    absolute = str(path.absolute())
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def is_reparse_point(entry_or_stat: _DirectoryEntry | os.stat_result) -> bool:
    if os.name == "nt":
        result = (
            entry_or_stat
            if isinstance(entry_or_stat, os.stat_result)
            else entry_or_stat.stat(follow_symlinks=False)
        )
        attributes = getattr(result, "st_file_attributes", 0)
        return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    if isinstance(entry_or_stat, os.stat_result):
        return stat.S_ISLNK(entry_or_stat.st_mode)
    return entry_or_stat.is_symlink()


def filesystem_identity(result: os.stat_result) -> str | None:
    if result.st_dev and result.st_ino:
        return f"{result.st_dev}:{result.st_ino}"
    return None
