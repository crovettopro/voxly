"""Asistente de primer arranque en DOS pasos, con diseño de producto.

  Paso 1 — Configure   : permisos (mic, accesibilidad), modelo de voz, IA opcional.
  Paso 2 — How to dictar: la tecla de dictado y los atajos, con un hero ⌘.

El estado se re-comprueba cada segundo con un NSTimer: cuando el usuario
concede Accesibilidad en Ajustes, la fila se marca sola sin reiniciar Voooxly.

Tres bugs de macOS que esta versión arregla:
- Ajustes del Sistema bloqueado por la ventana: al pulsar "Open Settings"
  escondemos el onboarding (orderOut); el NSTimer lo vuelve a mostrar cuando
  se concede el permiso (o cuando el usuario vuelve a la app).
- Hotkey mudo la primera vez: pynput arranca sin Accesibilidad y el event tap
  no se crea; conceder el permiso a mitad ni rearrancar el listener in-process
  basta (macOS no re-evalúa el permiso en el mismo proceso). Por eso on_finish
  RELANZA la app como proceso nuevo (ver app.py _on_onboarding_done), y por eso
  cerrar la ventana con el botón rojo también dispara finish_.
- Dos listeners a la vez: hotkey.stop() hace join() del listener viejo.

RESTRICCIONES de macOS aprendidas a base de crashes:
- NSWindow solo puede instanciarse en el hilo principal (igual que overlay.py).
- La ventana va a NIVEL FLOTANTE: app de barra sin Dock, así no se pierde atrás
  mientras descarga el modelo. Al abrir Ajustes se esconde (ver arriba).
"""
from __future__ import annotations

import logging
import threading
import time

import objc
from AppKit import (
    NSApplication,
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSFloatingWindowLevel,
    NSImageView,
    NSProgressIndicator,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSAttributedString, NSMakeRect, NSMakeSize, NSObject, NSTimer

from . import setup_checks, stt

log = logging.getLogger("voooxly.onboarding")

W, H = 580, 700
HEADER_H = 140
ROW_H = 84

# Paleta de marca. Violeta cálido + tintes para fondos y bordes.
ACCENT = NSColor.colorWithSRGBRed_green_blue_alpha_(0.42, 0.36, 0.90, 1.0)
ACCENT_DARK = NSColor.colorWithSRGBRed_green_blue_alpha_(0.32, 0.25, 0.78, 1.0)
ACCENT_TINT = NSColor.colorWithSRGBRed_green_blue_alpha_(0.42, 0.36, 0.90, 0.10)
INK = NSColor.colorWithSRGBRed_green_blue_alpha_(0.12, 0.11, 0.16, 1.0)
INK_SOFT = NSColor.colorWithSRGBRed_green_blue_alpha_(0.40, 0.39, 0.46, 1.0)
PAGE_BG = NSColor.colorWithSRGBRed_green_blue_alpha_(0.99, 0.99, 1.0, 1.0)
CARD_BG = NSColor.colorWithSRGBRed_green_blue_alpha_(0.98, 0.98, 1.0, 1.0)
CARD_BORDER = NSColor.colorWithSRGBRed_green_blue_alpha_(0.90, 0.89, 0.94, 1.0)
DISABLED_BG = NSColor.colorWithSRGBRed_green_blue_alpha_(0.80, 0.79, 0.85, 1.0)

# key, título, explicación, texto del botón. El orden es el de check_all().
STEPS = [
    ("mic", "Microphone",
     "So Voooxly can hear you. Your voice never leaves this Mac.", "Allow"),
    ("accessibility", "Accessibility",
     "Lets Voooxly type into any app and use the dictation hotkey.", "Open Settings"),
    ("model", "Speech model",
     "One-time 547 MB download. Runs fully offline after that.", "Download"),
    ("ai", "AI engine — optional",
     "Polish your dictation with Claude, ChatGPT, Gemini… Add it anytime from "
     "the menu bar (🎙 icon → AI engine). Works great without it.", "Check again"),
]


class OnboardingController(NSObject):
    """Controlador + ventana. Subclase de NSObject para ser target de los
    botones y delegate de la ventana (así cerrar con el botón rojo = finish_)."""

    def initWithFinish_(self, on_finish):
        self = objc.super(OnboardingController, self).init()
        if self is None:
            return None
        self._on_finish = on_finish
        self._rows = {}
        self._downloading = False
        self._timer = None
        self._page = 1
        self._hidden_for_settings = False
        self._hide_t = 0.0
        self._page1 = []
        self._page2 = []
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
        self._win.setTitle_("Welcome to Voooxly")
        self._win.setReleasedWhenClosed_(False)
        self._win.setLevel_(NSFloatingWindowLevel)
        self._win.setDelegate_(self)
        self._win.setBackgroundColor_(PAGE_BG)
        content = self._win.contentView()

        self._build_header(content)
        self._build_page1(content)
        self._build_page2(content)
        self._show_page(1)
        self._refresh()

    def _build_header(self, content):
        header = NSView.alloc().initWithFrame_(NSMakeRect(0, H - HEADER_H, W, HEADER_H))
        header.setWantsLayer_(True)
        # Degradado de marca; si CAGradientLayer no está, color plano.
        try:
            from Quartz import CAGradientLayer

            grad = CAGradientLayer.layer()
            grad.setFrame_(NSMakeRect(0, 0, W, HEADER_H))
            grad.setColors_([ACCENT_DARK.CGColor(), ACCENT.CGColor()])
            header.layer().addSublayer_(grad)
        except Exception:
            header.layer().setBackgroundColor_(ACCENT.CGColor())
        content.addSubview_(header)

        icon = NSImageView.alloc().initWithFrame_(NSMakeRect(32, H - 104, 64, 64))
        try:
            icon.setImage_(NSApplication.sharedApplication().applicationIconImage())
        except Exception:
            log.debug("No pude cargar el icono en el onboarding", exc_info=True)
        content.addSubview_(icon)

        self._header_title = _label(
            NSMakeRect(112, H - 66, W - 140, 32), "Welcome to Voooxly", 24,
            bold=True, color=NSColor.whiteColor())
        content.addSubview_(self._header_title)
        self._header_sub = _label(
            NSMakeRect(112, H - 98, W - 140, 24),
            "Dictate anywhere — Voooxly types what you say.", 13,
            color=NSColor.colorWithSRGBRed_green_blue_alpha_(1, 1, 1, 0.85))
        content.addSubview_(self._header_sub)

        # Indicador de paso (arriba a la derecha de la cabecera).
        self._step_label = _label(
            NSMakeRect(W - 156, H - 38, 132, 18), "STEP 1 OF 2", 11,
            bold=True, color=NSColor.colorWithSRGBRed_green_blue_alpha_(1, 1, 1, 0.85),
            align=1)
        content.addSubview_(self._step_label)

    # ---------------- página 1: configurar ----------------
    def _build_page1(self, content):
        top = H - HEADER_H  # 560
        sec = _label(NSMakeRect(40, top - 30, W - 80, 22),
                     "A couple of one-time steps:", 13, bold=True, color=INK)
        content.addSubview_(sec)
        self._page1.append(sec)

        y = top - 36
        for key, name, desc, action in STEPS:
            y -= ROW_H
            row = self._build_row(key, name, desc, action, y)
            content.addSubview_(row)
            self._page1.append(row)

        note = _label(
            NSMakeRect(40, 122, W - 80, 44),
            "Takes about 2 minutes. You can change any of this later from the "
            "menu bar (🎙 icon).", 12, color=INK_SOFT)
        _make_multiline(note)
        content.addSubview_(note)
        self._page1.append(note)

        self._done = _filled_button(
            NSMakeRect((W - 220) / 2, 28, 220, 44), "Continue →", self, "continue:")
        content.addSubview_(self._done)
        self._page1.append(self._done)

    # ---------------- página 2: cómo dictar ----------------
    def _build_page2(self, content):
        top = H - HEADER_H  # 560

        h1 = _label(NSMakeRect(40, 518, W - 80, 36), "You're all set.", 28,
                    bold=True, color=INK)
        content.addSubview_(h1)
        self._page2.append(h1)

        sub = _label(NSMakeRect(40, 492, W - 80, 22),
                     "Here's how to dictate. It lives in your menu bar.", 14,
                     color=INK_SOFT)
        content.addSubview_(sub)
        self._page2.append(sub)

        # ---- hero: la tecla de dictado ----
        hero = _keycap(NSMakeRect((W - 150) / 2, 330, 150, 150), "⌘", 60, big=True)
        content.addSubview_(hero)
        self._page2.append(hero)

        cap = _label(NSMakeRect(40, 300, W - 80, 22), "Hold the RIGHT ⌘ key", 13,
                     bold=True, color=INK, align=2)
        content.addSubview_(cap)
        self._page2.append(cap)

        instr = _label(
            NSMakeRect(50, 270, W - 100, 26),
            "speak, then release — your words get typed where the cursor is.",
            12, color=INK_SOFT, align=2)
        _make_multiline(instr)
        content.addSubview_(instr)
        self._page2.append(instr)

        # ---- tres atajos como tarjetas ----
        y = 268
        for keys, title, desc in (
            ("⌘ + Shift", "Hands-free", "Toggle dictation on/off without holding."),
            ("⌃⇧M", "Change mode", "Cycle 8 modes (verbatim, email, code…)."),
            ("Esc", "Cancel", "Throw away the dictation in progress."),
        ):
            y -= 60
            card = self._shortcut_card(y, keys, title, desc)
            content.addSubview_(card)
            self._page2.append(card)

        self._start = _filled_button(
            NSMakeRect((W - 220) / 2, 28, 220, 44), "Start dictating", self, "finish:")
        content.addSubview_(self._start)
        self._page2.append(self._start)

    def _shortcut_card(self, y, keys, title, desc):
        card = NSView.alloc().initWithFrame_(NSMakeRect(40, y, W - 80, 52))
        card.setWantsLayer_(True)
        card.layer().setBackgroundColor_(CARD_BG.CGColor())
        card.layer().setCornerRadius_(10.0)
        card.layer().setBorderWidth_(1.0)
        card.layer().setBorderColor_(CARD_BORDER.CGColor())

        cap = _keycap(NSMakeRect(12, 6, 96, 40), keys, 12)
        card.addSubview_(cap)
        card.addSubview_(_label(NSMakeRect(120, 28, W - 80 - 132, 18), title, 12, bold=True, color=INK))
        d = _label(NSMakeRect(120, 8, W - 80 - 132, 20), desc, 11, color=INK_SOFT)
        _make_multiline(d)
        card.addSubview_(d)
        return card

    def _build_row(self, key, name, desc, action, y):
        row = NSView.alloc().initWithFrame_(NSMakeRect(40, y, W - 80, ROW_H - 10))
        rw = W - 80

        status = _label(NSMakeRect(0, 44, 24, 22), "○", 16)
        row.addSubview_(status)
        row.addSubview_(_label(NSMakeRect(30, 44, 240, 22), name, 13, bold=True, color=INK))
        desc_lbl = _label(NSMakeRect(30, 6, rw - 150, 36), desc, 11, color=INK_SOFT)
        _make_multiline(desc_lbl)
        row.addSubview_(desc_lbl)

        btn = NSButton.alloc().initWithFrame_(NSMakeRect(rw - 130, 42, 130, 28))
        btn.setTitle_(action)
        btn.setBezelStyle_(1)
        btn.setTarget_(self)
        btn.setAction_(f"{key}:")
        row.addSubview_(btn)

        bar = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(30, 2, rw - 160, 12))
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
        # Escondemos el onboarding para que Ajustes del Sistema sea visible y
        # manejable: antes la ventana flotante se quedaba encima y bloqueaba.
        # El NSTimer (_refresh) lo vuelve a mostrar cuando se concede el permiso
        # o cuando el usuario vuelve a Voooxly.
        self._win.orderOut_(None)
        self._hidden_for_settings = True
        self._hide_t = time.monotonic()

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

    def continue_(self, _sender):
        """Página 1 → 2. Solo se habilita cuando los checks bloqueantes pasan."""
        self._show_page(2)

    def finish_(self, _sender):
        self._stop_timer()
        self._win.orderOut_(None)
        if self._on_finish:
            try:
                self._on_finish()
            except Exception:
                log.debug("callback on_finish falló", exc_info=True)

    def windowShouldClose_(self, _sender):
        # Cerrar con el botón rojo cuenta como finish: relanza la app (hotkey).
        self.finish_(None)
        return True

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
                ACCENT if check.ok else NSColor.tertiaryLabelColor())
            if not (check.key == "model" and self._downloading):
                row["button"].setEnabled_(not check.ok or check.key == "ai")
            if check.key == "model" and check.ok:
                row["bar"].setHidden_(True)
            if check.blocking and not check.ok:
                ready = False
        _style_filled_button(self._done, ready, "Continue →")

        # Re-mostrar la ventana si la escondimos para ir a Ajustes del Sistema.
        if self._hidden_for_settings:
            granted = setup_checks.has_accessibility()
            back = NSApplication.sharedApplication().isActive()
            elapsed = time.monotonic() - self._hide_t
            # El ">1.5s" evita re-mostrar en el mismo tick antes de que Ajustes
            # robe el foco. Se re-muestra al conceder el permiso o al volver.
            if granted or (back and elapsed > 1.5):
                self._hidden_for_settings = False
                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
                self._win.makeKeyAndOrderFront_(None)

    # ---------- páginas ----------
    def _show_page(self, n):
        self._page = n
        for v in self._page1:
            v.setHidden_(n != 1)
        for v in self._page2:
            v.setHidden_(n != 2)
        if n == 1:
            self._header_title.setStringValue_("Welcome to Voooxly")
            self._header_sub.setStringValue_(
                "Dictate anywhere — Voooxly types what you say.")
            self._step_label.setStringValue_("STEP 1 OF 2")
            self._done.setKeyEquivalent_("\r")
            self._start.setKeyEquivalent_("")
        else:
            self._header_title.setStringValue_("You're ready to dictate")
            self._header_sub.setStringValue_("Two keys are all you need.")
            self._step_label.setStringValue_("STEP 2 OF 2")
            self._done.setKeyEquivalent_("")
            self._start.setKeyEquivalent_("\r")

    def show(self):
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self._win.center()
        self._win.makeKeyAndOrderFront_(None)
        self._start_timer()


def _label(rect, text, size, bold=False, secondary=False, color=None, align=0):
    f = NSTextField.alloc().initWithFrame_(rect)
    f.setStringValue_(text)
    f.setBezeled_(False)
    f.setDrawsBackground_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    if color is not None:
        f.setTextColor_(color)
    elif secondary:
        f.setTextColor_(NSColor.secondaryLabelColor())
    if align:
        f.setAlignment_(align)
    return f


def _keycap(rect, text, size=13, big=False):
    """Tecla estilizada: rectángulo redondeado blanco con borde y sombra suave
    (profundidad). El texto centrado."""
    w = rect.size.width
    h = rect.size.height
    v = NSView.alloc().initWithFrame_(rect)
    v.setWantsLayer_(True)
    layer = v.layer()
    layer.setBackgroundColor_(NSColor.whiteColor().CGColor())
    layer.setCornerRadius_(18.0 if big else 10.0)
    layer.setBorderWidth_(1.0)
    layer.setBorderColor_(CARD_BORDER.CGColor())
    # sombra para que parezca una tecla real, no un cuadro plano
    try:
        layer.setShadowOpacity_(0.20 if big else 0.12)
        layer.setShadowRadius_(10.0 if big else 4.0)
        layer.setShadowOffset_(NSMakeSize(0, -3 if big else -1))
        layer.setShadowColor_(NSColor.colorWithSRGBRed_green_blue_alpha_(0.20, 0.18, 0.30, 1.0).CGColor())
    except Exception:
        pass
    lbl = _label(NSMakeRect(0, (h - (size + 8)) // 2, w, size + 8), text, size,
                 bold=True, color=INK, align=2)
    v.addSubview_(lbl)
    return v


def _filled_button(rect, title, target, action):
    """Botón CTA relleno con el color de marca y texto blanco bold."""
    b = NSButton.alloc().initWithFrame_(rect)
    b.setBordered_(False)
    b.setBezelStyle_(0)
    b.setWantsLayer_(True)
    b.layer().setCornerRadius_(10.0)
    b.setTarget_(target)
    b.setAction_(action)
    _style_filled_button(b, True, title)
    return b


def _style_filled_button(b, enabled, title):
    """Apariencia del botón relleno según esté habilitado o no (lo usa
    _refresh para el botón Continuar)."""
    bg = ACCENT if enabled else DISABLED_BG
    b.layer().setBackgroundColor_(bg.CGColor())
    fg = NSColor.whiteColor() if enabled else NSColor.colorWithSRGBRed_green_blue_alpha_(1, 1, 1, 0.55)
    attrs = {
        NSFontAttributeName: NSFont.boldSystemFontOfSize_(14),
        NSForegroundColorAttributeName: fg,
    }
    b.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(title, attrs))
    b.setEnabled_(enabled)


def _make_multiline(field):
    """Deja que un NSTextField ocupe varias líneas (para descripciones largas)."""
    try:
        field.setUsesSingleLineMode_(False)
        field.cell().setWraps_(True)
        field.cell().setLineBreakMode_(0)  # NSLineBreakByWordWrapping
    except Exception:
        pass


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