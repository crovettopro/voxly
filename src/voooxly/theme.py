"""Paleta de marca y widgets base, compartidos por las ventanas de AppKit.

Vivían en onboarding.py hasta que hubo una segunda ventana (Shortcuts).
Duplicar la paleta garantiza que se desincronice en el primer retoque de
marca, y acabar con dos ventanas de colores distintos en la misma app.

Los colores son los de voooxly.com y make-icon.py: teal + papel.
"""
from __future__ import annotations

from AppKit import (
    NSColor,
    NSFont,
    NSTextAlignmentCenter,
    NSTextAlignmentLeft,
    NSTextField,
    NSView,
)
from Foundation import NSMakeRect, NSMakeSize


def hex_(s, a=1.0):
    s = s.lstrip("#")
    return NSColor.colorWithSRGBRed_green_blue_alpha_(
        int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0, int(s[4:6], 16) / 255.0, a)


# ---- paleta de marca: teal + papel (voooxly.com / make-icon.py) ----
TEAL = hex_("#107A69")
TEAL_DARK = hex_("#085448")
INK = hex_("#1B241F")
INK_SOFT = hex_("#5F6B65")
INK_MUTED = hex_("#93A099")
INK_KEYCAP = hex_("#3F4A46")
PAGE_BG = hex_("#FCFDFC")
HAIRLINE = hex_("#EEF2F0")
DIVIDER = hex_("#E9EEEB")
BTN_BORDER = hex_("#DDE4E1")
BTN_GHOST_TEXT = hex_("#7C8A84")
MODEL_BTN_BG = hex_("#EDF5F3")
MODEL_BTN_BORDER = hex_("#BFDBD3")
PROGRESS_TRACK = hex_("#E4EEEB")
PENDING_RING = hex_("#CBD6D1")
CTA_DISABLED_BG = hex_("#EDF1EF")
CTA_DISABLED_TEXT = hex_("#AAB5B0")
KEYCAP_BG = hex_("#FFFFFF")
KEYCAP_BG2 = hex_("#EEF4F1")
KEYCAP_EDGE = hex_("#DEE9E4")


# ---------------- fuentes ----------------
def sf(size, weight=0.0):
    return NSFont.systemFontOfSize_weight_(float(size), float(weight))


def mono(size, weight=0.0):
    try:
        return NSFont.monospacedSystemFontOfSize_weight_(float(size), float(weight))
    except Exception:
        return NSFont.systemFontOfSize_(float(size))


def serif(size, semibold=False):
    for name in (("Iowan Old Style Bold",) if semibold else ()) + ("Iowan Old Style",):
        f = NSFont.fontWithName_size_(name, float(size))
        if f is not None:
            return f
    try:  # diseño serif del sistema (New York) como respaldo
        d = NSFont.systemFontOfSize_(float(size)).fontDescriptor()
        d = d.fontDescriptorWithDesign_("NSCTFontUIFontDesignSerif")
        f = NSFont.fontWithDescriptor_size_(d, float(size))
        if f is not None:
            return f
    except Exception:
        pass
    return NSFont.boldSystemFontOfSize_(float(size)) if semibold else NSFont.systemFontOfSize_(float(size))


# ---------------- helpers de vistas ----------------
def label(rect, text, font, color=None, align=NSTextAlignmentLeft, multiline=False):
    f = NSTextField.alloc().initWithFrame_(rect)
    f.setStringValue_(text)
    f.setBezeled_(False)
    f.setDrawsBackground_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setFont_(font)
    if color is not None:
        f.setTextColor_(color)
    if align != NSTextAlignmentLeft:
        f.setAlignment_(align)
    if multiline:
        _make_multiline(f)
    return f


def rule(rect, color):
    """Línea hairline (divisor / separador de filas)."""
    v = NSView.alloc().initWithFrame_(rect)
    v.setWantsLayer_(True)
    v.layer().setBackgroundColor_(color.CGColor())
    return v


def keycap(rect, text, glyph_font, radius, gradient=False):
    """Tecla estilizada: papel/blanco redondeado con borde y borde-inferior en
    relieve (profundidad). El glifo centrado."""
    w, h = rect.size.width, rect.size.height
    v = NSView.alloc().initWithFrame_(rect)
    v.setWantsLayer_(True)
    layer = v.layer()
    layer.setCornerRadius_(float(radius))
    layer.setBorderWidth_(1.0)
    layer.setBorderColor_(KEYCAP_EDGE.CGColor())
    if gradient:
        try:
            from Quartz import CAGradientLayer
            g = CAGradientLayer.layer()
            g.setFrame_(NSMakeRect(0, 0, w, h))
            g.setCornerRadius_(float(radius))
            g.setColors_([KEYCAP_BG.CGColor(), KEYCAP_BG2.CGColor()])
            layer.addSublayer_(g)
        except Exception:
            layer.setBackgroundColor_(KEYCAP_BG.CGColor())
    else:
        layer.setBackgroundColor_(KEYCAP_BG.CGColor())
    try:
        layer.setShadowOpacity_(0.22 if gradient else 0.10)
        layer.setShadowRadius_(12.0 if gradient else 3.0)
        layer.setShadowOffset_(NSMakeSize(0, -3 if gradient else -1))
        layer.setShadowColor_(TEAL_DARK.CGColor())
    except Exception:
        pass
    lbl = label(NSMakeRect(0, (h - (glyph_font.pointSize() + 8)) / 2, w, glyph_font.pointSize() + 8),
                text, glyph_font, TEAL_DARK if gradient else INK_KEYCAP, align=NSTextAlignmentCenter)
    v.addSubview_(lbl)
    return v


def _make_multiline(field):
    """Deja que un NSTextField ocupe varias líneas (para descripciones largas)."""
    try:
        field.setUsesSingleLineMode_(False)
        field.cell().setWraps_(True)
        field.cell().setLineBreakMode_(0)  # NSLineBreakByWordWrapping
    except Exception:
        pass
