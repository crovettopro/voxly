"""Generador del icono de Voxly: la "V" formada por barras de onda de voz.

Dibuja el squircle de macOS con gradiente + 5 barras blancas cuyo envolvente
forma una V. Genera variantes de color, el .icns final y el glyph template
de la barra de menú.

Uso:
  python scripts/make-icon.py preview            # 3 variantes → assets/preview/
  python scripts/make-icon.py build <variant>    # icns + menubar → assets/
"""
from __future__ import annotations

import math
import pathlib
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

VARIANTS = {
    # nombre: (color_top_left, color_bottom_right, color_barras)
    "violet": ((99, 102, 241), (217, 70, 239), (255, 255, 255)),      # indigo → fucsia
    "aqua": ((6, 182, 212), (59, 130, 246), (255, 255, 255)),         # cian → azul
    "neon": ((15, 23, 42), (30, 41, 59), (163, 230, 53)),             # midnight + lima
}

# Envolvente en V: alturas relativas de las 5 barras
BAR_HEIGHTS = [1.0, 0.60, 0.32, 0.60, 1.0]


def _gradient(size: int, c1, c2) -> Image.Image:
    """Gradiente diagonal c1 (arriba-izq) → c2 (abajo-dcha)."""
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))
    return img


def _lerp(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def draw_icon(size: int, c1, c2, cbar, squircle: bool = True, neon: bool = False) -> Image.Image:
    """Icono a resolución `size`. neon=True añade glow, gradiente por barra y
    ondas concéntricas de fondo (detalle "letrero de neón")."""
    S = 1024  # se dibuja a 1024 y se reescala (antialias)
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    grad = _gradient(S, c1, c2).convert("RGBA")

    if squircle:
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, S - 1, S - 1], radius=int(S * 0.2237), fill=255
        )
        icon.paste(grad, (0, 0), mask)
    else:
        icon = grad
        mask = None

    n = len(BAR_HEIGHTS)
    bar_w = S * 0.085
    gap = S * 0.055
    total_w = n * bar_w + (n - 1) * gap
    x0 = (S - total_w) / 2
    max_h = S * 0.52
    cy = S * 0.5

    CYAN = (34, 211, 238)
    # colores por barra: bordes = cbar (lima), centro = cian → acentúa la V
    bar_cols = [_lerp(cbar, CYAN, 1 - abs(i - (n - 1) / 2) / ((n - 1) / 2)) for i in range(n)] \
        if neon else [cbar] * n

    if neon:
        # ondas de sonido concéntricas, muy sutiles, tras las barras
        rip = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        rd = ImageDraw.Draw(rip)
        for r in (0.40, 0.52, 0.64):
            rr = S * r
            rd.ellipse([S / 2 - rr, cy - rr, S / 2 + rr, cy + rr],
                       outline=(255, 255, 255, 16), width=int(S * 0.007))
        if mask is not None:
            icon.paste(Image.alpha_composite(icon.crop((0, 0, S, S)), rip), (0, 0), mask)
        else:
            icon = Image.alpha_composite(icon, rip)

    # capa de barras (para poder duplicarla como glow)
    bars = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bars)
    for i, h in enumerate(BAR_HEIGHTS):
        bh = max_h * h
        x = x0 + i * (bar_w + gap)
        bd.rounded_rectangle(
            [x, cy - bh / 2, x + bar_w, cy + bh / 2],
            radius=bar_w / 2,
            fill=(*bar_cols[i], 255),
        )

    if neon:
        glow = bars.filter(ImageFilter.GaussianBlur(S * 0.028))
        glow.putalpha(glow.getchannel("A").point(lambda a: int(a * 0.75)))
        icon = Image.alpha_composite(icon, glow)
    icon = Image.alpha_composite(icon, bars)
    return icon.resize((size, size), Image.LANCZOS)


def preview():
    out = ASSETS / "preview"
    out.mkdir(parents=True, exist_ok=True)
    # composite: las 3 variantes lado a lado sobre fondo neutro
    pad, cell = 60, 360
    board = Image.new("RGB", (3 * cell + 4 * pad, cell + 2 * pad + 60), (245, 245, 247))
    from PIL import ImageFont

    for i, (name, (c1, c2, cb)) in enumerate(VARIANTS.items()):
        ic = draw_icon(cell, c1, c2, cb, neon=(name == "neon"))
        board.paste(ic, (pad + i * (cell + pad), pad), ic)
        (out / f"voxly-{name}.png").write_bytes(b"")
        draw_icon(512, c1, c2, cb, neon=(name == "neon")).save(out / f"voxly-{name}.png")
        d = ImageDraw.Draw(board)
        d.text(
            (pad + i * (cell + pad) + cell / 2, pad + cell + 22),
            name, fill=(60, 60, 67), anchor="mm",
        )
    path = out / "voxly-variants.png"
    board.save(path)
    print(path)


def build(variant: str):
    c1, c2, cb = VARIANTS[variant]
    ASSETS.mkdir(exist_ok=True)
    # --- .icns ---
    iconset = ASSETS / "Voxly.iconset"
    iconset.mkdir(exist_ok=True)
    for pts in (16, 32, 128, 256, 512):
        draw_icon(pts, c1, c2, cb, neon=(variant == "neon")).save(iconset / f"icon_{pts}x{pts}.png")
        draw_icon(pts * 2, c1, c2, cb, neon=(variant == "neon")).save(iconset / f"icon_{pts}x{pts}@2x.png")
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(ASSETS / "Voxly.icns")],
        check=True,
    )
    # --- glyph template de barra de menú (monocromo negro, alpha) ---
    for scale, name in ((1, "menubar.png"), (2, "menubar@2x.png")):
        S = 22 * scale
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        n = len(BAR_HEIGHTS)
        bar_w = S * 0.13
        gap = S * 0.075
        total_w = n * bar_w + (n - 1) * gap
        x0 = (S - total_w) / 2
        max_h = S * 0.78
        cy = S / 2
        for i, h in enumerate(BAR_HEIGHTS):
            bh = max_h * h
            x = x0 + i * (bar_w + gap)
            d.rounded_rectangle(
                [x, cy - bh / 2, x + bar_w, cy + bh / 2],
                radius=bar_w / 2,
                fill=(0, 0, 0, 255),
            )
        img.save(ASSETS / name)
    print(f"OK: assets/Voxly.icns + assets/menubar*.png (variante {variant})")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
    if cmd == "preview":
        preview()
    else:
        build(sys.argv[2])
