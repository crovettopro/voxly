"""Overlay HUD: ventana borderless que muestra la transcripción en vivo.

Implementado con AppKit (pyobjc). Debe crearse y usarse desde el main thread
(el runloop de rumps). Las llamadas desde otros hilos hacen dispatch al main.
"""
from __future__ import annotations

import logging

log = logging.getLogger("dictador.overlay")

try:
    from AppKit import (
        NSColor,
        NSFont,
        NSPanel,
        NSScreen,
        NSTextField,
        NSView,
        NSWindow,
        NSBackingStoreBuffered,
        NSBorderlessWindowMask,
        NSTitledWindowMask,
        NSVisualEffectView,
        NSVisualEffectMaterialPopover,
        NSVisualEffectBlendingModeBehindWindow,
    )
    from Foundation import NSRect, NSLog, NSObject, NSString
    from PyObjCTools import AppHelper
    import objc
    _HAVE_PYOBJC = True
except Exception as e:  # pragma: no cover
    log.warning("pyobjc no disponible: overlay desactivado (%s)", e)
    _HAVE_PYOBJC = False


class Overlay:
    def __init__(self, position: str = "bottom-right"):
        self.position = position
        self._win = None
        self._label = None
        self._built = False
        self._visible = False

    def _build(self):
        if not _HAVE_PYOBJC or self._built:
            return
        screen = NSScreen.mainScreen()
        frame = screen.visibleFrame()
        w, h = 520, 150
        if self.position == "bottom-right":
            x = frame.size.width - w - 24
            y = 24
        elif self.position == "top-right":
            x = frame.size.width - w - 24
            y = frame.size.height - h - 24
        else:
            x = (frame.size.width - w) / 2
            y = (frame.size.height - h) / 2

        win = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSRect(x, y, w, h),
            NSBorderlessWindowMask,
            NSBackingStoreBuffered,
            False,
        )
        win.setLevel_(19)  # NSFloatingWindowLevel, por encima de apps normales
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setHasShadow_(True)
        win.setCollectionBehavior_(1 << 4)  # NSWindowCollectionBehaviorCanJoinAllSpaces

        # vista de efecto (blur) de fondo
        try:
            blur = NSVisualEffectView.alloc().initWithFrame_(NSRect(0, 0, w, h))
            blur.setMaterial_(NSVisualEffectMaterialPopover)
            blur.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
            blur.setState_(1)  # active
            blur.setWantsLayer_(True)
            blur.setCornerRadius_(16)
            win.setContentView_(blur)
            container = blur
        except Exception:
            container = win.contentView()

        label = NSTextField.alloc().initWithFrame_(NSRect(16, 12, w - 32, h - 24))
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(True)
        label.setFont_(NSFont.systemFontOfSize_weight_(15.0, 0.0))
        label.setTextColor_(NSColor.whiteColor())
        label.setStringValue_("")
        container.addSubview_(label)

        self._win = win
        self._label = label
        self._built = True

    def show(self, text: str = "") -> None:
        if not _HAVE_PYOBJC:
            return
        self._build()
        if self._win is None:
            return
        self._dispatch_text(text)
        if not self._visible:
            self._win.performSelectorOnMainThread_withObject_waitUntilDone_(
                "orderFrontRegardless", None, False
            )
            self._visible = True

    def update(self, text: str) -> None:
        if not _HAVE_PYOBJC or not self._visible:
            return
        self._dispatch_text(text)

    def hide(self) -> None:
        if not _HAVE_PYOBJC or self._win is None:
            return
        if self._visible:
            self._win.performSelectorOnMainThread_withObject_waitUntilDone_(
                "orderOut:", None, False
            )
            self._visible = False

    def _dispatch_text(self, text: str) -> None:
        if self._label is None:
            return
        s = NSString.stringWithString_(text or "")
        self._label.performSelectorOnMainThread_withObject_waitUntilDone_(
            "setStringValue:", s, False
        )