import ctypes
import os
from collections.abc import Iterator
from ctypes import wintypes
from dataclasses import dataclass
from enum import StrEnum, auto
from hashlib import sha256
from pathlib import Path

from keepreadable.analysis.normalization import normalize_relative_path
from keepreadable.utilities.filesystem import extended_path


@dataclass(frozen=True, slots=True)
class VolumeInfo:
    serial: str | None
    label: str | None
    filesystem: str | None


def get_volume_info(path: Path) -> VolumeInfo:
    if os.name != "nt":
        return VolumeInfo(None, None, None)
    try:
        root = path.absolute().anchor
        if not root:
            return VolumeInfo(None, None, None)
        label = ctypes.create_unicode_buffer(261)
        filesystem = ctypes.create_unicode_buffer(261)
        serial = wintypes.DWORD()
        maximum_component_length = wintypes.DWORD()
        flags = wintypes.DWORD()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_information = kernel32.GetVolumeInformationW
        get_information.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        get_information.restype = wintypes.BOOL
        succeeded = get_information(
            root,
            label,
            len(label),
            ctypes.byref(serial),
            ctypes.byref(maximum_component_length),
            ctypes.byref(flags),
            filesystem,
            len(filesystem),
        )
        if not succeeded:
            return VolumeInfo(None, None, None)
        return VolumeInfo(f"{serial.value:08X}", label.value or None, filesystem.value or None)
    except OSError:
        return VolumeInfo(None, None, None)


def _path_without_anchor(path: Path) -> str:
    absolute = path.absolute()
    value = str(absolute)
    anchor = absolute.anchor
    return value[len(anchor) :] if anchor else value


def compute_root_fingerprint(root: Path, volume: VolumeInfo) -> str:
    relative = normalize_relative_path(_path_without_anchor(root))
    value = f"{volume.serial or ''}|{relative}"
    return sha256(value.encode("utf-8")).hexdigest()


class ArchiveAvailability(StrEnum):
    AVAILABLE = auto()
    RELOCATED = auto()
    UNAVAILABLE = auto()


@dataclass(frozen=True, slots=True)
class ResolvedRoot:
    availability: ArchiveAvailability
    path: Path | None


def is_root_available(path: Path) -> bool:
    if not os.path.isdir(extended_path(path)):
        return False
    try:
        with os.scandir(extended_path(path)):
            return True
    except OSError:
        return False


def iter_drive_roots() -> Iterator[Path]:
    if os.name != "nt":
        return
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        value = f"{letter}:\\"
        if os.path.exists(value):
            yield Path(value)


def resolve_archive_root(root_path: str, root_fingerprint: str) -> ResolvedRoot:
    configured = Path(root_path)
    if is_root_available(configured):
        fingerprint = compute_root_fingerprint(configured, get_volume_info(configured))
        if fingerprint == root_fingerprint:
            return ResolvedRoot(ArchiveAvailability.AVAILABLE, configured)

    relative = Path(_path_without_anchor(configured))
    configured_anchor = os.path.normcase(configured.absolute().anchor)
    for drive_root in iter_drive_roots():
        if os.path.normcase(drive_root.anchor) == configured_anchor:
            continue
        candidate = drive_root / relative
        if not is_root_available(candidate):
            continue
        fingerprint = compute_root_fingerprint(candidate, get_volume_info(candidate))
        if fingerprint == root_fingerprint:
            return ResolvedRoot(ArchiveAvailability.RELOCATED, candidate)
    return ResolvedRoot(ArchiveAvailability.UNAVAILABLE, None)
