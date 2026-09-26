from pathlib import Path

import pytest

from keepreadable.analysis.discovery import DiscoveryOptions, discover_files
from keepreadable.analysis.hashing import hash_file
from keepreadable.domain.enums import CheckStatus
from keepreadable.validators.base import ValidationDepth, ValidationResult
from keepreadable.validators.registry import ValidatorRegistry


def test_read_only_file_hashes_and_directory_named_like_file_is_walked(
    tmp_path: Path,
) -> None:
    path = tmp_path / "readonly.txt"
    path.write_bytes(b"read-only evidence")
    path.chmod(0o444)
    try:
        result = hash_file(path)
        assert result.bytes_read == len(b"read-only evidence")
        directory = tmp_path / "photo.jpg"
        directory.mkdir()
        (directory / "inside.txt").write_text("inside", encoding="utf-8")
        discovered = [item.relative_path for item in discover_files(tmp_path, DiscoveryOptions())]
        assert "photo.jpg" not in discovered
        assert "photo.jpg/inside.txt" in discovered
    finally:
        path.chmod(0o644)


@pytest.mark.parametrize("extension", ["jpg", "png", "bmp", "pdf", "zip", "docx", "mp4"])
def test_zero_byte_files_never_crash_validators(tmp_path: Path, extension: str) -> None:
    path = tmp_path / f"empty.{extension}"
    path.write_bytes(b"")
    validator, _support = ValidatorRegistry(ffmpeg=None).resolve(
        puid=None,
        extension=extension,
        mime=None,
    )
    result = validator.validate(path, depth=ValidationDepth.DEEP)
    assert isinstance(result, ValidationResult)
    assert result.structural in {
        CheckStatus.FAILED,
        CheckStatus.NOT_CHECKED,
        CheckStatus.UNAVAILABLE,
    }
