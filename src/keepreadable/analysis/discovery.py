import errno
import os
import stat
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from keepreadable.analysis.normalization import normalize_relative_path, relative_path_for_storage
from keepreadable.config.paths import data_dir
from keepreadable.utilities.cancellation import CancellationToken
from keepreadable.utilities.filesystem import (
    SkipReason,
    extended_path,
    filesystem_identity,
    is_reparse_point,
)


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    relative_path: str
    normalized_path: str
    size: int
    mtime_ns: int
    filesystem_identity: str | None


@dataclass(frozen=True, slots=True)
class SkippedItem:
    relative_path: str
    reason: SkipReason
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryOptions:
    follow_reparse_points: bool = False


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _relative(root: Path, path: Path) -> str:
    if _same_path(root, path):
        return "."
    try:
        return relative_path_for_storage(root, path)
    except ValueError:
        return path.name


def _reason_for_os_error(exc: OSError) -> SkipReason:
    if isinstance(exc, PermissionError):
        return SkipReason.PERMISSION_DENIED
    if isinstance(exc, FileNotFoundError):
        return SkipReason.VANISHED
    if exc.errno == errno.ENAMETOOLONG or getattr(exc, "winerror", None) == 206:
        return SkipReason.PATH_TOO_LONG
    return SkipReason.OS_ERROR


class _DiscoveryWalker:
    def __init__(
        self,
        root: Path,
        options: DiscoveryOptions,
        cancel: CancellationToken | None,
        on_skip: Callable[[SkippedItem], None] | None,
    ) -> None:
        self.root = root.absolute()
        self.options = options
        self.cancel = cancel
        self.on_skip = on_skip
        self.excluded_data_dir = data_dir().absolute()
        self.visited: set[tuple[int, int]] = set()
        self.files_seen = 0

    def report(self, path: Path, reason: SkipReason, detail: str | None = None) -> None:
        if self.on_skip is not None:
            self.on_skip(SkippedItem(_relative(self.root, path), reason, detail))

    def scan_directory(self, path: Path) -> list[tuple[Path, os.DirEntry[str]]]:
        if self.cancel is not None:
            self.cancel.raise_if_cancelled()
        try:
            with os.scandir(extended_path(path)) as iterator:
                entries = sorted(iterator, key=lambda item: item.name)
        except OSError as exc:
            self.report(path, _reason_for_os_error(exc), str(exc))
            return []
        return [(path / entry.name, entry) for entry in entries]

    def stat_entry(self, path: Path, entry: os.DirEntry[str]) -> os.stat_result | None:
        try:
            return entry.stat(follow_symlinks=False)
        except OSError as exc:
            self.report(path, _reason_for_os_error(exc), str(exc))
            return None

    def follow_reparse(
        self, path: Path, entry: os.DirEntry[str], result: os.stat_result
    ) -> os.stat_result | None:
        if not is_reparse_point(result):
            return result
        if not self.options.follow_reparse_points:
            self.report(path, SkipReason.REPARSE_POINT)
            return None
        try:
            target = entry.stat(follow_symlinks=True)
        except OSError as exc:
            self.report(path, _reason_for_os_error(exc), str(exc))
            return None
        if not stat.S_ISDIR(target.st_mode):
            self.report(path, SkipReason.REPARSE_POINT)
            return None
        return target

    def queue_directory(
        self,
        path: Path,
        result: os.stat_result,
        stack: list[tuple[Path, os.DirEntry[str] | None]],
    ) -> None:
        if _same_path(path, self.excluded_data_dir):
            return
        identity = (result.st_dev, result.st_ino)
        if all(identity) and identity in self.visited:
            self.report(path, SkipReason.REPARSE_POINT)
            return
        if all(identity):
            self.visited.add(identity)
        stack.append((path, None))

    def discovered_file(self, path: Path, result: os.stat_result) -> DiscoveredFile | None:
        self.files_seen += 1
        if self.files_seen % 256 == 0 and self.cancel is not None:
            self.cancel.raise_if_cancelled()
        if not stat.S_ISREG(result.st_mode):
            self.report(path, SkipReason.NOT_A_REGULAR_FILE)
            return None
        relative_path = relative_path_for_storage(self.root, path)
        return DiscoveredFile(
            relative_path=relative_path,
            normalized_path=normalize_relative_path(relative_path),
            size=result.st_size,
            mtime_ns=result.st_mtime_ns,
            filesystem_identity=filesystem_identity(result),
        )

    def walk(self) -> Iterator[DiscoveredFile]:
        root_stat = os.stat(extended_path(self.root), follow_symlinks=False)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise NotADirectoryError(str(self.root))
        if _same_path(self.root, self.excluded_data_dir):
            return
        if root_stat.st_dev and root_stat.st_ino:
            self.visited.add((root_stat.st_dev, root_stat.st_ino))
        stack: list[tuple[Path, os.DirEntry[str] | None]] = [(self.root, None)]
        while stack:
            path, entry = stack.pop()
            if entry is None:
                stack.extend(reversed(self.scan_directory(path)))
                continue
            result = self.stat_entry(path, entry)
            if result is None:
                continue
            result = self.follow_reparse(path, entry, result)
            if result is None:
                continue
            if stat.S_ISDIR(result.st_mode):
                self.queue_directory(path, result, stack)
                continue
            discovered = self.discovered_file(path, result)
            if discovered is not None:
                yield discovered


def discover_files(
    root: Path,
    options: DiscoveryOptions,
    *,
    cancel: CancellationToken | None = None,
    on_skip: Callable[[SkippedItem], None] | None = None,
) -> Iterator[DiscoveredFile]:
    yield from _DiscoveryWalker(root, options, cancel, on_skip).walk()
