import os
from pathlib import Path

import pytest

from keepreadable.analysis import archive_identity
from keepreadable.analysis.archive_identity import (
    ArchiveAvailability,
    ResolvedRoot,
    VolumeInfo,
    compute_root_fingerprint,
    resolve_archive_root,
)


def test_fingerprint_is_deterministic_and_path_case_insensitive(tmp_path: Path) -> None:
    volume = VolumeInfo("A1B2", "Data", "NTFS")
    first = compute_root_fingerprint(tmp_path / "MixedCase", volume)
    second = compute_root_fingerprint(Path(str(tmp_path / "mixedcase").upper()), volume)
    assert first == second
    assert len(first) == 64


def test_fingerprint_changes_with_volume_serial(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    first = compute_root_fingerprint(root, VolumeInfo("ONE", None, None))
    second = compute_root_fingerprint(root, VolumeInfo("TWO", None, None))
    assert first != second


def test_resolve_available_root(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    root.mkdir()
    fingerprint = compute_root_fingerprint(root, archive_identity.get_volume_info(root))
    assert resolve_archive_root(str(root), fingerprint) == ResolvedRoot(
        ArchiveAvailability.AVAILABLE, root
    )


def test_resolve_unavailable_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive_identity, "iter_drive_roots", lambda: iter(()))
    result = resolve_archive_root(str(tmp_path / "missing"), "0" * 64)
    assert result == ResolvedRoot(ArchiveAvailability.UNAVAILABLE, None)


@pytest.mark.skipif(os.name != "nt", reason="drive relocation is Windows-specific")
def test_resolve_relocated_root(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = Path("C:/Archive")
    relocated = Path("Z:/Archive")
    volume = VolumeInfo("SERIAL", "Data", "NTFS")
    fingerprint = compute_root_fingerprint(configured, volume)

    monkeypatch.setattr(
        archive_identity,
        "is_root_available",
        lambda path: os.path.normcase(str(path)) == os.path.normcase(str(relocated)),
    )
    monkeypatch.setattr(
        archive_identity,
        "iter_drive_roots",
        lambda: iter([Path("C:/"), Path("Z:/")]),
    )
    monkeypatch.setattr(archive_identity, "get_volume_info", lambda _path: volume)

    assert resolve_archive_root(str(configured), fingerprint) == ResolvedRoot(
        ArchiveAvailability.RELOCATED, relocated
    )
