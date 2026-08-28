from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "etc" / "logo.png"
TARGET = ROOT / "build" / "piper-tray" / "piper-tray.ico"
SIZES = [
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
]


def main() -> int:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE) as image:
        image.convert("RGBA").save(TARGET, format="ICO", sizes=SIZES)
    print(TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
