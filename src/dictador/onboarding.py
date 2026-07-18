"""Asistente de primer arranque: guía permisos, modelo de voz y motor de IA.

Una sola ventana con una fila por requisito y su botón de acción. El estado se
re-comprueba cada segundo con un NSTimer: cuando el usuario concede Accesibilidad
en Ajustes, la fila se marca sola sin tener que reiniciar Voxly.

RESTRICCIÓN: NSWindow solo puede instanciarse en el hilo principal — igual que el
NSPanel de overlay.py. Hacerlo desde otro hilo aborta el proceso con SIGABRT.
"""
from __future__ import annotations

import logging
import threading

import objc
from AppKit import (
    NSApplication,
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSFont,
    NSProgressIndicator,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRect, NSObject, NSTimer

from . import setup_checks, stt

log = logging.getLogger("dictador.onboarding")

W, H = 540, 500
ROW_H = 78

# key, título, explicación, texto del botón. El orden es el de check_all().
STEPS = [
    ("mic", "Microphone",
     "So Voxly can hear you. Your voice never leaves this Mac.", "Allow"),
    ("accessibility", "Accessibility",
     "Lets Voxly use the hotkey and paste text into any app.", "Open Settings"),
    ("model", "Speech model",
     "One-time 547 MB download. Transcription runs offline.", "Download"),
    ("ai", "AI engine (optional)",
     "Ollama or an API key polishes your dictation. Works fine without it.", "Check again"),
]


class OnboardingController(NSObject):
    """Controlador + ventana. Subclase de NSObject para poder ser target de botones."""

    def initWithFinish_(self, on_finish):
        self = objc.super(OnboardingController, self).init()
        if self is None:
            return None
        self._on_finish = on_finish
        self._rows = {}
        self._downloading = False
        self._timer = None
        self._build()
        return self

    # ---------- construcción ----------
    def _build(self):
        self._win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        self._win.setTitle_("Welcome to Voxly")
        self._win.setReleasedWhenClosed_(False)
        content = self._win.contentView()

        content.addSubview_(_label(
            NSMakeRect(24, H - 62, W - 48, 26), "Let's get you dictating", 20, bold=True))
        content.addSubview_(_label(
            NSMakeRect(24, H - 86, W - 48, 20),
            "A few one-time steps and you're set.", 12, secondary=True))

        y = H - 104
        for key, name, desc, action in STEPS:
            y -= ROW_H
            content.addSubview_(self._build_row(key, name, desc, action, y))

        self._hint = _label(
            NSMakeRect(24, 26, W - 190, 34),
            "You're ready — hold the right ⌘ key, speak, and let go. Esc cancels.", 12)
        self._hint.setHidden_(True)
        content.addSubview_(self._hint)

        self._done = NSButton.alloc().initWithFrame_(NSMakeRect(W - 150, 22, 126, 32))
        self._done.setTitle_("Start dictating")
        self._done.setBezelStyle_(1)
        self._done.setKeyEquivalent_("\r")
        self._done.setTarget_(self)
        self._done.setAction_("finish:")
        content.addSubview_(self._done)

        self._refresh()

    def _build_row(self, key, name, desc, action, y):
        row = NSView.alloc().initWithFrame_(NSMakeRect(24, y, W - 48, ROW_H - 10))
        rw = W - 48

        status = _label(NSMakeRect(0, 40, 22, 20), "○", 15)
        row.addSubview_(status)
        row.addSubview_(_label(NSMakeRect(24, 40, 260, 20), name, 13, bold=True))
        row.addSubview_(_label(NSMakeRect(24, 18, rw - 150, 20), desc, 11, secondary=True))

        btn = NSButton.alloc().initWithFrame_(NSMakeRect(rw - 124, 36, 124, 26))
        btn.setTitle_(action)
        btn.setBezelStyle_(1)
        btn.setTarget_(self)
        btn.setAction_(f"{key}:")
        row.addSubview_(btn)

        bar = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(24, 2, rw - 150, 12))
        bar.setStyle_(0)              # NSProgressIndicatorStyleBar
        bar.setIndeterminate_(False)
        bar.setMinValue_(0.0)
        bar.setMaxValue_(100.0)
        bar.setHidden_(True)
        row.addSubview_(bar)

        self._rows[key] = {"status": status, "button": btn, "bar": bar}
        return row

    # ---------- acciones de los botones (selectores mic:, accessibility:, ...) ----------
    def mic_(self, _sender):
        setup_checks.request_microphone()

    def accessibility_(self, _sender):
        setup_checks.open_accessibility_settings()

    def model_(self, _sender):
        if self._downloading:
            return
        self._downloading = True
        row = self._rows["model"]
        row["button"].setEnabled_(False)
        row["button"].setTitle_("Downloading…")
        row["bar"].setHidden_(False)
        threading.Thread(target=self._download_model, daemon=True).start()

    def ai_(self, _sender):
        from . import refine

        refine.detect_backend(force=True)
        self._refresh()

    def finish_(self, _sender):
        self._stop_timer()
        self._win.orderOut_(None)
        if self._on_finish:
            try:
                self._on_finish()
            except Exception:
                log.debug("callback on_finish falló", exc_info=True)

    # ---------- descarga del modelo ----------
    def _download_model(self):
        """Corre en hilo secundario; todo toque de UI se reenvía al principal."""
        try:
            stt.ensure_model(progress_cb=lambda pct:
                             self.performSelectorOnMainThread_withObject_waitUntilDone_(
                                 "updateProgress:", pct, False))
        except Exception as e:
            log.error("Descarga del modelo falló: %s", e)
        finally:
            self._downloading = False
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "downloadFinished:", None, False)

    def updateProgress_(self, pct):
        try:
            self._rows["model"]["bar"].setDoubleValue_(float(pct))
        except Exception:
            pass

    def downloadFinished_(self, _arg):
        row = self._rows["model"]
        row["button"].setTitle_("Download")
        self._refresh()

    # ---------- refresco periódico ----------
    def tick_(self, _timer):
        self._refresh()

    def _start_timer(self):
        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self, "tick:", None, True)

    def _stop_timer(self):
        if self._timer is not None:
            try:
                self._timer.invalidate()
            except Exception:
                pass
            self._timer = None

    def _refresh(self):
        ready = True
        for check in setup_checks.check_all():
            row = self._rows.get(check.key)
            if row is None:
                continue
            row["status"].setStringValue_("●" if check.ok else "○")
            row["status"].setTextColor_(
                NSColor.systemGreenColor() if check.ok else NSColor.tertiaryLabelColor())
            # El paso de IA se puede re-comprobar siempre; los demás solo si faltan.
            if not (check.key == "model" and self._downloading):
                row["button"].setEnabled_(not check.ok or check.key == "ai")
            if check.key == "model" and check.ok:
                row["bar"].setHidden_(True)
            if check.blocking and not check.ok:
                ready = False
        self._done.setEnabled_(ready)
        self._hint.setHidden_(not ready)

    def show(self):
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self._win.center()
        self._win.makeKeyAndOrderFront_(None)
        self._start_timer()


def _label(rect, text, size, bold=False, secondary=False):
    f = NSTextField.alloc().initWithFrame_(rect)
    f.setStringValue_(text)
    f.setBezeled_(False)
    f.setDrawsBackground_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    if secondary:
        f.setTextColor_(NSColor.secondaryLabelColor())
    return f


# Referencia global: sin ella el recolector se lleva la ventana y desaparece sola.
_controller = None


def show_onboarding(on_finish=None) -> None:
    """Muestra el asistente. DEBE llamarse desde el hilo principal."""
    global _controller
    try:
        _controller = OnboardingController.alloc().initWithFinish_(on_finish)
        _controller.show()
    except Exception as e:
        log.error("No pude mostrar el onboarding: %s", e)
