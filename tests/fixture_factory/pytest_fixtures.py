from pathlib import Path

import pytest

from tests.fixture_factory import (
    make_docx,
    make_jpeg,
    make_pdf,
    make_png,
    make_wav_stdlib,
    make_xlsx,
    make_zip,
)


@pytest.fixture(scope="session")
def fixture_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("keepreadable-fixtures")
    make_jpeg(root / "image.jpg")
    make_png(root / "image.png")
    make_zip(root / "archive.zip", {"entry.txt": b"content"})
    make_pdf(root / "document.pdf")
    make_docx(root / "document.docx")
    make_xlsx(root / "workbook.xlsx")
    make_wav_stdlib(root / "audio.wav")
    return root
