import unicodedata
from pathlib import Path

from keepreadable.analysis.normalization import (
    extension_of,
    normalize_relative_path,
    relative_path_for_storage,
)


def test_normalize_separators_prefixes_and_case() -> None:
    assert normalize_relative_path("./Folder\\Mixed.TXT") == "folder/mixed.txt"
    assert normalize_relative_path("/Folder/File") == "folder/file"


def test_normalize_uses_nfc_and_casefold() -> None:
    nfc = "Café/STRASSE.TXT"
    nfd = unicodedata.normalize("NFD", nfc)
    assert normalize_relative_path(nfc) == normalize_relative_path(nfd)
    assert normalize_relative_path("Straße.txt") == "strasse.txt"


def test_relative_path_for_storage_preserves_case_and_normalizes_unicode(
    tmp_path: Path,
) -> None:
    path = tmp_path / unicodedata.normalize("NFD", "Café.TXT")
    assert relative_path_for_storage(tmp_path, path) == "Café.TXT"


def test_extension_without_dot_is_lowercase() -> None:
    assert extension_of("Folder/Archive.TAR.GZ") == "gz"
    assert extension_of("README") == ""
    assert extension_of("name.") == ""
    assert extension_of(".gitignore") == ""
