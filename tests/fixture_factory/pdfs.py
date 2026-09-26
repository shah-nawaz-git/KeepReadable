from pathlib import Path

import pikepdf

from tests.fixture_factory.corruption import truncate_file


def make_pdf(path: Path, pages: int = 3) -> Path:
    pdf = pikepdf.Pdf.new()
    font = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name("/Font"),
            Subtype=pikepdf.Name("/Type1"),
            BaseFont=pikepdf.Name("/Helvetica"),
        )
    )
    for index in range(pages):
        page = pdf.add_blank_page(page_size=(300, 200))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        content = (
            f"BT /F1 14 Tf 30 150 Td (Fixture page {index + 1}) Tj ET 20 20 260 160 re S\n"
        ).encode("ascii")
        page.Contents = pdf.make_stream(content)
    pdf.save(path)
    pdf.close()
    return path


def make_encrypted_pdf(path: Path) -> Path:
    temporary = path.with_suffix(".plain.pdf")
    make_pdf(temporary, pages=1)
    with pikepdf.open(temporary) as pdf:
        pdf.save(path, encryption=pikepdf.Encryption(owner="o", user="u", R=6))
    temporary.unlink()
    return path


def make_truncated_pdf(path: Path, pages: int = 3) -> Path:
    make_pdf(path, pages)
    return truncate_file(path, 0.55)


def make_malformed_pdf(path: Path) -> Path:
    make_pdf(path, pages=2)
    data = bytearray(path.read_bytes())
    for marker in (b"xref", b"trailer", b"/Pages"):
        start = data.find(marker)
        if start >= 0:
            data[start : start + len(marker)] = b"X" * len(marker)
    path.write_bytes(data)
    try:
        with pikepdf.open(path):
            pass
    except pikepdf.PdfError:
        return path
    data = path.read_bytes()
    path.write_bytes(data[: max(32, len(data) // 3)])
    try:
        with pikepdf.open(path):
            pass
    except pikepdf.PdfError:
        return path
    raise AssertionError("malformed PDF fixture remained readable")


def make_pdf_with_missing_eof(path: Path) -> Path:
    make_pdf(path, pages=1)
    data = path.read_bytes()
    marker = data.rfind(b"%%EOF")
    if marker < 0:
        raise ValueError("PDF end marker not found")
    path.write_bytes(data[:marker] + data[marker + len(b"%%EOF") :])
    return path
