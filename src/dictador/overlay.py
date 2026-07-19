"""Overlay HUD: ventana flotante con título de estado + cuerpo, estilo Wispr.

GOTCHA macOS 26: un NSPanel (borderless O con título) NUNCA llega al window
server — isVisible=True pero CGWindowList no lo lista y no se pinta ni un
píxel (verificado con capturas). Un NSWindow borderless sí se compone, con
capa CALayer oscura redondeada (el blur NSVisualEffectView era parte de la
receta fantasma). No volver a NSPanel.

Diseño: título corto con glyph acentuado por color (● rojo grabando, ✦ ámbar
procesando, ✓ teal pegado, ❯ teal al cambiar de modo) + cuerpo atenuado. La
ventana crece/encoge con el contenido, anclada abajo-derecha.

Debe construirse en el main thread (runloop de rumps); show/update/hide se
pueden llamar desde cualquier hilo (AppHelper.callAfter hace el dispatch).
"""
from __future__ import annotations

import logging

log = logging.getLogger("dictador.overlay")

try:
    from AppKit import (
        NSColor,
        NSFont,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSMutableParagraphStyle,
        NSParagraphStyleAttributeName,
        NSScreen,
        NSTextField,
        NSView,
        NSWindow,
        NSBackingStoreBuffered,
        NSBorderlessWindowMask,
    )
    from Foundation import NSMutableAttributedString, NSRect
    from PyObjCTools import AppHelper
    _HAVE_PYOBJC = True
except Exception as e:  # pragma: no cover
    log.warning("pyobjc no disponible: overlay desactivado (%s)", e)
    _HAVE_PYOBJC = False

W = 520
PAD_X = 18
PAD_Y = 14
MIN_H = 52
MAX_H = 300
MARGIN = 24

# Color del glyph inicial del título según lo que anuncia
_ACCENTS = {
    "●": (0.91, 0.26, 0.24),   # grabando — rojo
    "✦": (0.82, 0.54, 0.13),   # procesando — ámbar (--signal de la marca)
    "✓": (0.18, 0.64, 0.55),   # hecho — teal (--resolved de la marca)
    "❯": (0.18, 0.64, 0.55),   # cambio de modo — teal
}


class Overlay:
    def __init__(self, position: str = "bottom-right"):
        self.position = position
        self._win = None
        self._label = None
        self._built = False
        self._visible = False
        self._title = ""
        self._body = ""

    # --- ciclo de vida (main thread) ---
    def build(self):
        """Construye el NSWindow. DEBE llamarse desde el main thread, una vez."""
        self._build()

    def _build(self):
        if not _HAVE_PYOBJC or self._built:
            return
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSRect((0, 0), (W, MIN_H)),
            NSBorderlessWindowMask,
            NSBackingStoreBuffered,
            False,
        )
        win.setReleasedWhenClosed_(False)
        win.setLevel_(19)  # NSFloatingWindowLevel
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setHasShadow_(True)
        win.setCollectionBehavior_(1 << 4)  # CanJoinAllSpaces

        container = NSView.alloc().initWithFrame_(NSRect((0, 0), (W, MIN_H)))
        container.setWantsLayer_(True)
        layer = container.layer()
        layer.setBackgroundColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.07, 0.90).CGColor()
        )
        layer.setCornerRadius_(14.0)
        layer.setBorderWidth_(1.0)
        layer.setBorderColor_(
            NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.09).CGColor()
        )
        win.setContentView_(container)

        label = NSTextField.alloc().initWithFrame_(
            NSRect((PAD_X, PAD_Y), (W - 2 * PAD_X, MIN_H - 2 * PAD_Y))
        )
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setStringValue_("")
        container.addSubview_(label)

        self._win = win
        self._label = label
        self._built = True

    # --- API pública (cualquier hilo) ---
    def show(self, text: str = "", title: str | None = None) -> None:
        """Muestra el HUD. `title` fija la línea de estado; None la quita."""
        if not _HAVE_PYOBJC or not self._built:
            return
        self._title = title or ""
        self._body = text or ""
        self._visible = True
        AppHelper.callAfter(self._render, True)

    def update(self, text: str) -> None:
        """Actualiza el cuerpo conservando el título (p.ej. parciales en vivo)."""
        if not _HAVE_PYOBJC or not self._visible:
            return
        self._body = text or ""
        AppHelper.callAfter(self._render, False)

    def hide(self) -> None:
        if not _HAVE_PYOBJC or self._win is None or not self._visible:
            return
        self._visible = False
        AppHelper.callAfter(self._do_hide)

    # --- render (siempre en main thread) ---
    def _do_hide(self):
        try:
            self._win.orderOut_(None)
        except Exception:
            log.debug("hide falló", exc_info=True)

    def _attributed(self):
        text = NSMutableAttributedString.alloc().init()
        if self._title:
            para = NSMutableParagraphStyle.alloc().init()
            para.setParagraphSpacing_(5.0)
            t = NSMutableAttributedString.alloc().initWithString_attributes_(
                self._title + ("\n" if self._body else ""),
                {
                    NSFontAttributeName: NSFont.systemFontOfSize_weight_(15.0, 0.3),
                    NSForegroundColorAttributeName: NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.96),
                    NSParagraphStyleAttributeName: para,
                },
            )
            accent = _ACCENTS.get(self._title[:1])
            if accent:
                t.addAttribute_value_range_(
                    NSForegroundColorAttributeName,
                    NSColor.colorWithCalibratedRed_green_blue_alpha_(*accent, 1.0),
                    (0, 1),
                )
            text.appendAttributedString_(t)
        if self._body:
            body_alpha = 0.70 if self._title else 0.92
            b = NSMutableAttributedString.alloc().initWithString_attributes_(
                self._body,
                {
                    NSFontAttributeName: NSFont.systemFontOfSize_weight_(13.5, 0.0),
                    NSForegroundColorAttributeName: NSColor.colorWithCalibratedWhite_alpha_(1.0, body_alpha),
                },
            )
            text.appendAttributedString_(b)
        return text

    def _render(self, reorder: bool):
        if self._win is None or self._label is None:
            return
        try:
            attr = self._attributed()
            # altura del texto a ancho fijo → la ventana se ajusta al contenido
            bounds = attr.boundingRectWithSize_options_(
                (W - 2 * PAD_X, 100000), 1  # NSStringDrawingUsesLineFragmentOrigin
            )
            text_h = min(max(int(bounds.size.height) + 2, MIN_H - 2 * PAD_Y), MAX_H)
            win_h = text_h + 2 * PAD_Y

            frame = NSScreen.mainScreen().visibleFrame()
            if self.position == "top-right":
                x = frame.origin.x + frame.size.width - W - MARGIN
                y = frame.origin.y + frame.size.height - win_h - MARGIN
            elif self.position == "center":
                x = frame.origin.x + (frame.size.width - W) / 2
                y = frame.origin.y + (frame.size.height - win_h) / 2
            else:  # bottom-right (anclada abajo: crece hacia arriba)
                x = frame.origin.x + frame.size.width - W - MARGIN
                y = frame.origin.y + MARGIN

            self._win.setFrame_display_(NSRect((x, y), (W, win_h)), True)
            self._label.setFrame_(NSRect((PAD_X, PAD_Y), (W - 2 * PAD_X, text_h)))
            self._label.setAttributedStringValue_(attr)
            if reorder:
                self._win.orderFrontRegardless()
        except Exception:
            log.debug("render del overlay falló", exc_info=True)
