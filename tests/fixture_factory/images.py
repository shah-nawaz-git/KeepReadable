import random
from pathlib import Path

from PIL import Image, ImageDraw


def _image(size: tuple[int, int], seed: int) -> Image.Image:
    randomizer = random.Random(seed)
    image = Image.new("RGB", size)
    pixels = image.load()
    assert pixels is not None
    for y in range(size[1]):
        for x in range(size[0]):
            pixels[x, y] = (
                (x * 255 // max(1, size[0] - 1)),
                (y * 255 // max(1, size[1] - 1)),
                randomizer.randrange(32, 224),
            )
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, size[0] // 2, size[1] // 2), outline="white", width=2)
    draw.ellipse((size[0] // 2, size[1] // 3, size[0] - 3, size[1] - 3), fill="navy")
    return image


def _save(path: Path, format_name: str, size: tuple[int, int], seed: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _image(size, seed) as image:
        image.save(path, format=format_name)
    return path


def make_jpeg(path: Path, size: tuple[int, int] = (64, 48), seed: int = 1) -> Path:
    return _save(path, "JPEG", size, seed)


def make_png(path: Path, size: tuple[int, int] = (64, 48), seed: int = 1) -> Path:
    return _save(path, "PNG", size, seed)


def make_tiff(path: Path, size: tuple[int, int] = (64, 48), seed: int = 1) -> Path:
    return _save(path, "TIFF", size, seed)


def make_bmp(path: Path, size: tuple[int, int] = (64, 48), seed: int = 1) -> Path:
    return _save(path, "BMP", size, seed)


def make_multiframe_tiff(path: Path, seed: int = 1) -> Path:
    frames = [_image((64, 48), seed + index) for index in range(3)]
    try:
        frames[0].save(path, format="TIFF", save_all=True, append_images=frames[1:])
    finally:
        for frame in frames:
            frame.close()
    return path


def make_jpeg_with_exif(path: Path, seed: int = 1) -> Path:
    exif = Image.Exif()
    exif[270] = "KeepReadable fixture"
    exif[271] = "KeepReadable"
    with _image((64, 48), seed) as image:
        image.save(path, format="JPEG", exif=exif)
    return path
