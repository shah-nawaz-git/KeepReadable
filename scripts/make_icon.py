from pathlib import Path

from PIL import Image, ImageDraw


def make_icon(destination: Path) -> None:
    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((16, 16, 240, 240), radius=48, fill="#2F6FED")
    shield = [(128, 48), (198, 76), (188, 164), (128, 214), (68, 164), (58, 76)]
    draw.polygon(shield, fill="white")
    draw.line((88, 126, 116, 154, 170, 96), fill="#2F6FED", width=18, joint="curve")
    destination.mkdir(parents=True, exist_ok=True)
    image.save(destination / "icon.png", format="PNG")
    image.save(
        destination / "icon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)]
    )


if __name__ == "__main__":
    make_icon(Path(__file__).parents[1] / "src" / "keepreadable" / "resources")
