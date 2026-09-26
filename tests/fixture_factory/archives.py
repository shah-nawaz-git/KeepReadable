import struct
import zipfile
from pathlib import Path


def _info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def make_zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(_info(name), content)
    return path


def damage_central_directory(path: Path) -> Path:
    data = path.read_bytes()
    position = data.rfind(b"PK\x05\x06")
    if position < 0:
        raise ValueError("end record not found")
    path.write_bytes(data[:position] + b"XX\x05\x06" + data[position + 4 :])
    return path


def make_bad_crc_zip(path: Path) -> Path:
    info = zipfile.ZipInfo("entry.bin", (2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(info, b"measurable content")
    data = bytearray(path.read_bytes())
    header = struct.unpack_from("<IHHHHHIIIHH", data, 0)
    data_offset = 30 + header[-2] + header[-1]
    data[data_offset] ^= 0xFF
    path.write_bytes(data)
    return path


def make_encrypted_flag_zip(path: Path) -> Path:
    info = zipfile.ZipInfo("entry.bin", (2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(info, b"flagged content")
    data = bytearray(path.read_bytes())
    local = data.find(b"PK\x03\x04")
    central = data.find(b"PK\x01\x02")
    local_flags = struct.unpack_from("<H", data, local + 6)[0] | 1
    central_flags = struct.unpack_from("<H", data, central + 8)[0] | 1
    struct.pack_into("<H", data, local + 6, local_flags)
    struct.pack_into("<H", data, central + 8, central_flags)
    path.write_bytes(data)
    return path


def make_high_ratio_zip(path: Path, size_mb: int = 20) -> Path:
    return make_zip(path, {"zeros.bin": b"\0" * (size_mb * 1024 * 1024)})


def make_traversal_zip(path: Path) -> Path:
    make_zip(
        path,
        {
            "../escape.txt": b"one",
            "C:\\abs.txt": b"two",
            "..\\win.txt": b"three",
        },
    )
    data = path.read_bytes().replace(b"C:/abs.txt", b"C:\\abs.txt")
    path.write_bytes(data.replace(b"../win.txt", b"..\\win.txt"))
    return path


def make_many_entries_zip(path: Path, n: int) -> Path:
    return make_zip(path, {f"entry-{index:04}.txt": b"x" for index in range(n)})


def make_empty_zip(path: Path) -> Path:
    return make_zip(path, {})
