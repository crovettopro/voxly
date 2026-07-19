"""Generador del icono de Voxly: la comilla editorial — el habla hecha texto.

Marca compartida con la landing (usevoxly.vercel.app): comilla doble de
apertura serif (Iowan Old Style, la misma familia del sitio) en color papel
sobre squircle teal. Sustituye a las barras de onda v1, demasiado parecidas
al logo de Wispr Flow.

Uso:
  python scripts/make-icon.py preview   # PNG 512 de control → assets/preview/
  python scripts/make-icon.py build     # .icns + menubar template → assets/
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

# Paleta de marca (la de la landing)
TEAL_TOP = (16, 122, 105)      # esquina sup-izq, un punto más luminoso
TEAL_BOTTOM = (8, 84, 72)      # esquina inf-dcha
PAPER = (237, 240, 238)        # #EDF0EE

# La misma serif que el sitio; Georgia como red de seguridad
FONTS = [
    ("/System/Library/Fonts/Supplemental/Iowan Old Style.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Georgia.ttf", 0),
]

GLYPH = "“"  # comilla doble de apertura


def _font(px: int) -> ImageFont.FreeTypeFont:
    for path, index in FONTS:
        try:
            return ImageFont.truetype(path, px, index=index)
        except OSError:
            continue
    raise SystemExit("No hay serif del sistema disponible (Iowan/Georgia)")


def _gradient(size: int, c1, c2) -> Image.Image:
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))
    return img


def _glyph_layer(S: int, color, width_ratio: float) -> Image.Image:
    """Capa transparente con la comilla centrada ÓPTICAMENTE.

    Las métricas del glyph “ mienten según la fuente (vive pegado al
    ascender), así que no se confía en textbbox para colocar: se dibuja en
    un lienzo sobrado, se recorta a la tinta REAL (alpha) y esa caja se pega
    centrada en el lienzo final. Inmune a rarezas de métrica.
    """
    big = S * 3
    scratch = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(scratch)
    d.text((big // 2, big // 2), GLYPH, font=_font(S), fill=(*color, 255), anchor="mm")
    box = scratch.getbbox()
    if box is None:
        raise SystemExit("La fuente no tiene tinta para el glyph “")
    ink = scratch.crop(box)
    # escalar la tinta al ancho objetivo conservando proporción
    target_w = int(S * width_ratio)
    target_h = int(ink.height * target_w / ink.width)
    ink = ink.resize((target_w, target_h), Image.LANCZOS)
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    layer.paste(ink, ((S - target_w) // 2, (S - target_h) // 2), ink)
    return layer


def draw_icon(size: int) -> Image.Image:
    S = 1024  # se dibuja a 1024 y se reescala (antialias)
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    grad = _gradient(S, TEAL_TOP, TEAL_BOTTOM).convert("RGBA")
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, S - 1, S - 1], radius=int(S * 0.2237), fill=255
    )
    icon.paste(grad, (0, 0), mask)
    icon = Image.alpha_composite(icon, _glyph_layer(S, PAPER, 0.52))
    return icon.resize((size, size), Image.LANCZOS)


def draw_menubar(scale: int) -> Image.Image:
    """Glyph template: comilla negra sobre alpha; macOS lo tiñe él solo."""
    S = 22 * scale
    big = _glyph_layer(22 * 8, (0, 0, 0), 0.62)  # se dibuja grande y se baja
    return big.resize((S, S), Image.LANCZOS)


def preview():
    out = ASSETS / "preview"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "voxly-quote.png"
    draw_icon(512).save(path)
    print(path)


def build():
    ASSETS.mkdir(exist_ok=True)
    iconset = ASSETS / "Voxly.iconset"
    iconset.mkdir(exist_ok=True)
    for pts in (16, 32, 128, 256, 512):
        draw_icon(pts).save(iconset / f"icon_{pts}x{pts}.png")
        draw_icon(pts * 2).save(iconset / f"icon_{pts}x{pts}@2x.png")
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(ASSETS / "Voxly.icns")],
        check=True,
    )
    for scale, name in ((1, "menubar.png"), (2, "menubar@2x.png")):
        draw_menubar(scale).save(ASSETS / name)
    print("OK: assets/Voxly.icns + assets/menubar*.png (marca comilla)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
    if cmd == "preview":
        preview()
    else:
        build()
