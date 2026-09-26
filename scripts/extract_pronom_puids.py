import argparse
import json
from collections.abc import Callable
from pathlib import Path
from xml.etree import ElementTree

Record = tuple[str, str, frozenset[str], frozenset[str]]


def records(path: Path) -> list[Record]:
    root = ElementTree.parse(path).getroot()
    output = []
    for element in root.iter():
        if not element.tag.endswith("FileFormat"):
            continue
        puid = element.attrib.get("PUID", "")
        name = element.attrib.get("Name", "")
        extensions = frozenset(
            child.text.casefold()
            for child in element
            if child.tag.endswith("Extension") and child.text
        )
        mimes = frozenset(
            value.strip().casefold()
            for value in element.attrib.get("MIMEType", "").split(",")
            if value.strip()
        )
        if puid:
            output.append((puid, name, extensions, mimes))
    return output


def _has_extension(*extensions: str) -> Callable[[Record], bool]:
    expected = frozenset(extensions)
    return lambda record: bool(record[2] & expected)


def family_predicates() -> dict[str, Callable[[Record], bool]]:
    return {
        "JPEG": lambda r: (
            _has_extension("jpg", "jpeg")(r)
            and any(
                term in r[1].casefold() for term in ("jpeg", "exchangeable image", "still picture")
            )
        ),
        "PNG": lambda r: (
            _has_extension("png")(r) and "portable network graphics" in r[1].casefold()
        ),
        "TIFF": lambda r: r[1].casefold() == "tagged image file format",
        "BMP": lambda r: _has_extension("bmp")(r) and r[1].casefold().startswith("windows bitmap"),
        "MP3": lambda r: r[1].casefold() == "mpeg 1/2 audio layer 3",
        "WAV": lambda r: (
            _has_extension("wav")(r)
            and (
                r[1].casefold().startswith("waveform audio") or "broadcast wave" in r[1].casefold()
            )
        ),
        "FLAC": lambda r: _has_extension("flac")(r) and r[1].casefold().startswith("flac"),
        "MP4": lambda r: bool(r[2] & {"mp4", "m4v"}) and "mpeg-4 media file" in r[1].casefold(),
        "MOV": lambda r: _has_extension("mov")(r) and "quicktime" in r[1].casefold(),
        "AVI": lambda r: _has_extension("avi")(r) and "audio/video interleaved" in r[1].casefold(),
        "PDF": lambda r: (
            _has_extension("pdf")(r)
            and (
                "portable document format" in r[1].casefold() or "pdf portfolio" in r[1].casefold()
            )
        ),
        "ZIP": lambda r: r[1].casefold() == "zip format" or "deflate64" in r[1].casefold(),
        "DOCX": lambda r: bool(r[2] & {"docx", "docm"}) and "owner file" not in r[1].casefold(),
        "XLSX": lambda r: bool(r[2] & {"xlsx", "xlsm"}),
        "PPTX": lambda r: bool(r[2] & {"pptx", "pptm"}),
    }


def extract(path: Path) -> dict[str, list[str]]:
    source = records(path)
    return {
        family: sorted(record[0] for record in source if predicate(record))
        for family, predicate in family_predicates().items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("signature", type=Path)
    args = parser.parse_args()
    families = extract(args.signature)
    print(json.dumps(families, indent=2))
    print("counts:", ", ".join(f"{name}={len(puids)}" for name, puids in families.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
