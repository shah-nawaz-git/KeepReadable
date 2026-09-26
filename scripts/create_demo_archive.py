import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tests.fixture_factory import (  # noqa: E402
    damage_central_directory,
    ffmpeg_available,
    make_avi,
    make_bmp,
    make_docx,
    make_encrypted_flag_zip,
    make_encrypted_pdf,
    make_flac,
    make_jpeg,
    make_malformed_pdf,
    make_mov,
    make_mp3,
    make_mp4,
    make_pdf,
    make_png,
    make_png_named_jpg,
    make_pptx,
    make_text,
    make_tiff,
    make_truncated_pdf,
    make_unknown_binary,
    make_wav,
    make_wav_stdlib,
    make_xlsx,
    make_zip,
    remove_zip_member,
    truncate_file,
    zero_range,
)
from tests.fixture_factory.ooxml import make_fake_ole  # noqa: E402


def create_demo_archive(
    destination: Path,
    *,
    seed: int = 42,
    media: bool | None = None,
    large: int = 0,
    manifest: bool = False,
) -> dict[str, object]:
    destination.mkdir(parents=True, exist_ok=True)
    folders = {
        name: destination / name
        for name in (
            "Photos/2004",
            "Photos/2011",
            "Documents/University",
            "Documents/Scans",
            "Video",
            "Audio",
            "Downloads",
            "Old Computer",
        )
    }
    for folder in folders.values():
        folder.mkdir(parents=True, exist_ok=True)
    damaged: dict[str, str] = {}
    for index in range(18):
        make_jpeg(folders["Photos/2004"] / f"holiday-{index:02}.jpg", seed=seed + index)
    for index in range(12):
        make_png(folders["Photos/2011"] / f"family-{index:02}.png", seed=seed + 100 + index)
    make_tiff(folders["Documents/Scans"] / "certificate.tiff", seed=seed)
    make_bmp(folders["Old Computer"] / "wallpaper.bmp", seed=seed)
    truncate_file(
        make_jpeg(folders["Photos/2004"] / "truncated-photo.jpg", seed=seed),
        0.62,
    )
    damaged["Photos/2004/truncated-photo.jpg"] = "Unreadable image data"
    make_png_named_jpg(folders["Downloads"] / "image-with-wrong-extension.jpg", seed)
    damaged["Downloads/image-with-wrong-extension.jpg"] = "Extension mismatch review"
    make_zip(
        folders["Downloads"] / "course-materials.zip",
        {"notes.txt": b"Course notes", "data.csv": b"name,value\nalpha,1\n"},
    )
    damage_central_directory(
        make_zip(folders["Downloads"] / "broken-package.zip", {"file.txt": b"data"})
    )
    damaged["Downloads/broken-package.zip"] = "ZIP structure failure"
    make_encrypted_flag_zip(folders["Downloads"] / "protected-package.zip")
    damaged["Downloads/protected-package.zip"] = "Protected content"
    make_pdf(folders["Documents/University"] / "thesis.pdf", pages=6)
    make_malformed_pdf(folders["Documents/Scans"] / "malformed-scan.pdf")
    damaged["Documents/Scans/malformed-scan.pdf"] = "PDF structure failure"
    make_truncated_pdf(folders["Documents/Scans"] / "truncated-scan.pdf")
    damaged["Documents/Scans/truncated-scan.pdf"] = "Unexpected truncation"
    make_encrypted_pdf(folders["Documents/University"] / "protected-notes.pdf")
    damaged["Documents/University/protected-notes.pdf"] = "Protected content"
    make_docx(folders["Documents/University"] / "essay.docx")
    make_xlsx(folders["Documents/University"] / "grades.xlsx")
    make_pptx(folders["Documents/University"] / "presentation.pptx")
    source_docx = make_docx(folders["Documents/University"] / "source.docx")
    remove_zip_member(
        source_docx,
        folders["Documents/University"] / "missing-main.docx",
        "word/document.xml",
    )
    source_docx.unlink()
    damaged["Documents/University/missing-main.docx"] = "OOXML structure failure"
    make_fake_ole(folders["Old Computer"] / "report.doc")
    damaged["Old Computer/report.doc"] = "Unknown legacy binary container"
    make_wav_stdlib(folders["Audio"] / "memo-stdlib.wav")
    include_media = ffmpeg_available() if media is None else media
    if include_media and ffmpeg_available():
        make_mp4(folders["Video"] / "birthday.mp4")
        make_mov(folders["Video"] / "school-play.mov")
        make_avi(folders["Video"] / "old-camera.avi")
        make_mp3(folders["Audio"] / "recording.mp3", seconds=3)
        make_wav(folders["Audio"] / "interview.wav")
        make_flac(folders["Audio"] / "music.flac")
        truncate_file(make_mp4(folders["Video"] / "truncated-video.mp4"), 0.6)
        damaged["Video/truncated-video.mp4"] = "Media truncation evidence"
        changed_mp3 = make_mp3(folders["Audio"] / "changed-audio.mp3", seconds=3)
        size = changed_mp3.stat().st_size
        zero_range(changed_mp3, size // 2 - 2048, 4096)
        damaged["Audio/changed-audio.mp3"] = "Media decode failure"
    make_unknown_binary(folders["Downloads"] / "mystery", seed=seed)
    damaged["Downloads/mystery"] = "Unknown format"
    duplicate = make_jpeg(folders["Photos/2011"] / "portrait.jpg", seed=seed + 500)
    shutil.copyfile(duplicate, folders["Documents/Scans"] / "portrait-copy.jpg")
    damaged["Documents/Scans/portrait-copy.jpg"] = "Byte-identical copy"
    texts = {
        "Documents/University/reading-list.md": "# Reading list\n\n- Archive studies\n",
        "Documents/University/results.csv": "name,score\nAlex,91\nSam,88\n",
        "Old Computer/README.txt": "Files copied from an older family computer.\n",
        "Downloads/notes.txt": "Synthetic demonstration content.\n",
    }
    for relative, content in texts.items():
        make_text(destination / relative, content)
    current_count = sum(path.is_file() for path in destination.rglob("*"))
    for index in range(max(0, 120 - current_count)):
        make_text(
            folders["Documents/University"] / f"note-{index:03}.txt",
            f"Synthetic note {index} generated with seed {seed}.\n",
        )
    for index in range(large):
        if index % 10 == 0:
            make_jpeg(
                folders["Photos/2011"] / f"large-{index:05}.jpg",
                size=(32, 24),
                seed=seed + 1000 + index,
            )
        else:
            make_text(
                folders["Documents/Scans"] / f"large-{index:05}.txt",
                f"Synthetic performance fixture {index}.\n",
            )
    expected_outcomes = {
        path.relative_to(destination).as_posix(): {
            "health": "healthy",
            "finding_codes": [],
        }
        for path in destination.rglob("*")
        if path.is_file()
    }
    expected_overrides = {
        "Photos/2004/truncated-photo.jpg": ("unreadable", ["unexpected_truncation"]),
        "Downloads/image-with-wrong-extension.jpg": ("review", ["extension_mismatch"]),
        "Downloads/broken-package.zip": ("unreadable", ["structural_failure"]),
        "Downloads/protected-package.zip": ("review", ["protected_content"]),
        "Documents/Scans/malformed-scan.pdf": ("unreadable", ["structural_failure"]),
        "Documents/Scans/truncated-scan.pdf": ("unreadable", ["unexpected_truncation"]),
        "Documents/University/protected-notes.pdf": ("review", ["protected_content"]),
        "Documents/University/missing-main.docx": ("unreadable", ["structural_failure"]),
        "Downloads/mystery": ("unknown", ["unknown_format"]),
        "Old Computer/report.doc": ("unknown", ["unknown_format"]),
    }
    if include_media and ffmpeg_available():
        expected_overrides.update(
            {
                "Video/truncated-video.mp4": (
                    "unreadable",
                    ["unexpected_truncation"],
                ),
                "Audio/changed-audio.mp3": ("unreadable", ["decode_failure"]),
            }
        )
    for relative_path, (health, finding_codes) in expected_overrides.items():
        if relative_path in expected_outcomes:
            expected_outcomes[relative_path] = {
                "health": health,
                "finding_codes": finding_codes,
            }
    return {
        "destination": str(destination),
        "seed": seed,
        "media_included": bool(include_media and ffmpeg_available()),
        "file_count": sum(path.is_file() for path in destination.rglob("*")),
        "intentionally_damaged": damaged,
        "expected_outcomes": expected_outcomes,
        "duplicate_groups": [["Photos/2011/portrait.jpg", "Documents/Scans/portrait-copy.jpg"]],
        "manifest_requested": manifest,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dest", type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--media", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--large", type=int, default=0)
    parser.add_argument("--manifest", action="store_true")
    args = parser.parse_args()
    manifest = create_demo_archive(
        args.dest,
        seed=args.seed,
        media=args.media,
        large=args.large,
    )
    if args.manifest:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        media_note = "with media" if manifest["media_included"] else "without FFmpeg media"
        print(f"Created {manifest['file_count']} files at {args.dest} ({media_note}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
