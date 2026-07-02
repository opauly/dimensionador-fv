"""
One-time script: inverts firma_white.png → firma_dark.png using Pillow.
Run once after placing firma_white.png in proposals/assets/.

Usage:
    python tools/invert_signature.py
"""
from pathlib import Path
from PIL import Image, ImageOps


ASSETS_DIR = Path(__file__).parent.parent / "proposals" / "assets"
INPUT = ASSETS_DIR / "firma_white.png"
OUTPUT = ASSETS_DIR / "firma_dark.png"


def invert_signature():
    if not INPUT.exists():
        print(f"✗ No encontrado: {INPUT}")
        print("  Copia firma_white.png a proposals/assets/ y vuelve a correr.")
        return

    img = Image.open(INPUT).convert("RGBA")

    r, g, b, a = img.split()
    rgb = Image.merge("RGB", (r, g, b))
    inverted = ImageOps.invert(rgb)
    result = Image.merge("RGBA", (*inverted.split(), a))
    result.save(OUTPUT)
    print(f"✓ Guardado: {OUTPUT}")


if __name__ == "__main__":
    invert_signature()
