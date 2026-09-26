from collections.abc import Callable
from pathlib import Path

from keepreadable.domain.enums import CheckStatus
from keepreadable.validators.base import EvidenceCode, ValidationDepth, ValidationResult
from keepreadable.validators.zip_archive import ZipValidator
from tests.fixture_factory import (
    damage_central_directory,
    make_bad_crc_zip,
    make_empty_zip,
    make_encrypted_flag_zip,
    make_high_ratio_zip,
    make_many_entries_zip,
    make_traversal_zip,
    make_zip,
)


def validator(max_entries: int = 100) -> ZipValidator:
    return ZipValidator(max_entries, 100 * 1024 * 1024, 10.0)


def test_valid_and_empty_zip(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    for path in (
        make_zip(tmp_path / "valid.zip", {"a.txt": b"alpha", "b.txt": b"beta"}),
        make_empty_zip(tmp_path / "empty.zip"),
    ):
        result = record_validation(validator().validate(path, depth=ValidationDepth.DEEP))
        assert result.structural is CheckStatus.PASSED
        assert result.readability is CheckStatus.PASSED


def test_damaged_central_directory_fails_structure(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    path = damage_central_directory(make_zip(tmp_path / "damaged.zip", {"a": b"x"}))
    result = record_validation(validator().validate(path, depth=ValidationDepth.DEEP))
    assert result.structural is CheckStatus.FAILED
    assert EvidenceCode.STRUCTURAL_FAILURE in result.codes


def test_bad_crc_only_fails_in_deep_mode(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    path = make_bad_crc_zip(tmp_path / "bad-crc.zip")
    quick = record_validation(validator().validate(path, depth=ValidationDepth.QUICK))
    deep = record_validation(validator().validate(path, depth=ValidationDepth.DEEP))
    assert quick.structural is CheckStatus.PASSED
    assert quick.readability is CheckStatus.NOT_CHECKED
    assert deep.structural is CheckStatus.PASSED
    assert deep.readability is CheckStatus.FAILED
    assert EvidenceCode.DECODE_FAILURE in deep.codes
    assert "CRC check failed" in deep.summary


def test_encrypted_flag_is_protected_without_crc_check(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    path = make_encrypted_flag_zip(tmp_path / "encrypted.zip")
    result = record_validation(validator().validate(path, depth=ValidationDepth.DEEP))
    assert result.readability is CheckStatus.PROTECTED
    assert EvidenceCode.PROTECTED_CONTENT in result.codes
    assert "entry CRC checks" in result.checks_not_performed
    assert "entry CRC checks" not in result.checks_performed


def test_ratio_traversal_and_entry_count_warnings(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    ratio = record_validation(
        validator().validate(
            make_high_ratio_zip(tmp_path / "ratio.zip", size_mb=2),
            depth=ValidationDepth.QUICK,
        )
    )
    traversal = record_validation(
        validator().validate(
            make_traversal_zip(tmp_path / "traversal.zip"), depth=ValidationDepth.QUICK
        )
    )
    many = record_validation(
        validator(max_entries=2).validate(
            make_many_entries_zip(tmp_path / "many.zip", 3), depth=ValidationDepth.QUICK
        )
    )
    assert "suspicious compression ratio" in ratio.warnings
    assert "entry names that could escape a destination folder" in traversal.warnings
    assert set(traversal.details["unsafe_entry_names"]) == {
        "../escape.txt",
        "C:\\abs.txt",
        "..\\win.txt",
    }
    assert traversal.structural is CheckStatus.PASSED
    assert any("entry count" in warning for warning in many.warnings)


def test_validation_never_extracts_files(
    tmp_path: Path,
    record_validation: Callable[[ValidationResult], ValidationResult],
) -> None:
    path = make_zip(tmp_path / "archive.zip", {"folder/file.txt": b"content"})
    before = {item.name for item in tmp_path.iterdir()}
    record_validation(validator().validate(path, depth=ValidationDepth.DEEP))
    after = {item.name for item in tmp_path.iterdir()}
    assert after == before
