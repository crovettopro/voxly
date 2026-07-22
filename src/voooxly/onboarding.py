"""Asistente de primer arranque en DOS pasos, con diseño de producto.

  Paso 1 — Configure   : permisos (mic, accesibilidad), modelo de voz, IA opcional.
  Paso 2 — How to dictar: la tecla de dictado y los atajos, con un hero ⌘.

Estética (rediseño v2): marca **teal + papel** (voooxly.com + el icono de la app),
títulos en serif (Iowan Old Style), filas separadas por hairlines en vez de
tarjetas. El estado se re-comprueba cada segundo con un NSTimer: cuando el usuario
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

Botones "muertos" en macOS 26 (Tahoe) — el bug que más costó:
  La app es accesoria (LSUIElement) y show() se llama ANTES de que arranque el
  run loop de rumps. En macOS 26 eso deja la ventana visible pero NO activa/key,
  y el window server se traga el primer clic como "activar app" en vez de
  entregárselo al botón: mic y accesibilidad parecían no responder. La cura es
  promover la app a Regular mientras dura el onboarding (ventana de primer plano
  de verdad, con foco y tile en el Dock — que además hace útil el minimizar) y
  re-activar UNA vez el run loop ya corre. Al terminar se restaura Accessory.
  El botón de micrófono, además, manda a Ajustes si el permiso ya se denegó:
  requestAccess solo abre el prompt cuando está "sin decidir".

IA opcional: "Connect AI" delega en un callback (on_connect_ai) que abre el
selector de proveedor + key del app.py (flujo ya probado). Lo conectado persiste
tras el relanzamiento. Nadie tiene IA en el primer arranque, así que NO es un
botón de "test" — es un "conectar", opcional, que convierte el dictado en algo
más que transcribir (limpia, formatea y reescribe lo dictado).
"""
from __future__ import annotations

import logging
import threading
import time

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSFloatingWindowLevel,
    NSImageView,
    NSTextAlignmentCenter,
    NSTextAlignmentLeft,
    NSTextAlignmentRight,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSAttributedString, NSMakeRect, NSMakeSize, NSObject, NSTimer

from . import setup_checks, stt
from .theme import (  # noqa: F401  (se re-exportan: los usan las páginas)
    BTN_BORDER, BTN_GHOST_TEXT, CTA_DISABLED_BG, CTA_DISABLED_TEXT, DIVIDER,
    HAIRLINE, INK, INK_KEYCAP, INK_MUTED, INK_SOFT, KEYCAP_BG, KEYCAP_BG2,
    KEYCAP_EDGE, MODEL_BTN_BG, MODEL_BTN_BORDER, PAGE_BG, PENDING_RING,
    PROGRESS_TRACK, TEAL, TEAL_DARK,
)
from .theme import hex_ as _hex
from .theme import keycap as _keycap
from .theme import label as _label
from .theme import mono as _mono
from .theme import rule as _rule
from .theme import serif as _serif
from .theme import sf as _sf

log = logging.getLogger("voooxly.onboarding")

W, H = 580, 700
PAD = 40


def _y(top, h):
    """Convierte una 'y desde arriba' (como en el diseño) al origen abajo-izquierda."""
    return H - top - h


# key, título, explicación, texto del botón, estilo. El orden es el de check_all().
STEPS = [
    ("mic", "Microphone",
     "So Voooxly can hear you. Your voice never leaves this Mac.", "Allow", "ghost"),
    ("accessibility", "Accessibility",
     "Lets Voooxly type into any app and use the dictation hotkey.", "Open Settings", "ghost"),
    ("model", "Speech model",
     "One-time 547 MB download. Runs fully offline after that.", "Download", "tint"),
    ("ai", "AI engine",
     "Optional, but it makes Voooxly more than a dictation tool: connect Claude, "
     "ChatGPT or Gemini and it cleans up, formats and rewrites what you say. "
     "You can also add it later from the menu bar.", "Connect AI", "text"),
]


class OnboardingController(NSObject):
    """Controlador + ventana. Subclase de NSObject para ser target de los
    botones y delegate de la ventana (así cerrar con el botón rojo = finish_)."""

    def initWithFinish_(self, on_finish):
        return self.initWithFinish_connectAI_(on_finish, None)

    def initWithFinish_connectAI_(self, on_finish, on_connect_ai):
        self = objc.super(OnboardingController, self).init()
        if self is None:
            return None
        self._on_finish = on_finish
        self._on_connect_ai = on_connect_ai
        self._rows = {}
        self._row_views = {}
        self._downloading = False
        self._timer = None
        self._page = 1
        self._hidden_for_settings = False
        self._hide_t = 0.0
        self._page1 = []
        self._page2 = []
        self._model_fill = None
        self._model_track_w = 1.0
        self._model_pct = None
        self._build()
        return self

    # ---------- construcción ----------
    def _build(self):
        self._win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable,
            NSBackingStoreBuffered,
            False,
        )
        self._win.setTitle_("Welcome to Voooxly")
        self._win.setReleasedWhenClosed_(False)
        self._win.setLevel_(NSFloatingWindowLevel)
        self._win.setDelegate_(self)
        self._win.setBackgroundColor_(PAGE_BG)
        content = self._win.contentView()

        # STEP label compartido (arriba a la derecha, ambas páginas).
        self._step_label = _label(NSMakeRect(W - PAD - 160, _y(38, 12), 160, 12),
                                  "STEP 1 OF 2", _mono(10, 0.3), INK_MUTED,
                                  align=NSTextAlignmentRight)
        content.addSubview_(self._step_label)

        self._build_page1(content)
        self._build_page2(content)
        self._show_page(1)
        self._refresh()

    # ---------------- página 1: configurar ----------------
    def _build_page1(self, content):
        add = self._page1.append

        icon = NSImageView.alloc().initWithFrame_(NSMakeRect(PAD, _y(32, 60), 60, 60))
        try:
            icon.setImage_(NSApplication.sharedApplication().applicationIconImage())
        except Exception:
            log.debug("No pude cargar el icono en el onboarding", exc_info=True)
        content.addSubview_(icon); add(icon)

        title = _label(NSMakeRect(PAD, _y(114, 34), W - 2 * PAD, 34),
                       "Welcome to Voooxly", _serif(27, semibold=True), INK)
        content.addSubview_(title); add(title)
        sub = _label(NSMakeRect(PAD, _y(154, 20), W - 2 * PAD, 20),
                     "Dictate anywhere — Voooxly types what you say.", _sf(14.5), INK_SOFT)
        content.addSubview_(sub); add(sub)

        div = _rule(NSMakeRect(PAD, _y(196, 1), W - 2 * PAD, 1), DIVIDER)
        content.addSubview_(div); add(div)

        sec = _label(NSMakeRect(PAD, _y(215, 14), W - 2 * PAD, 14),
                     "A COUPLE OF ONE-TIME STEPS", _sf(11, 0.3), INK_MUTED)
        content.addSubview_(sec); add(sec)

        rows_h = {"mic": 62, "accessibility": 62, "model": 72, "ai": 96}
        t = 241
        first = True
        for key, name, desc, action, style in STEPS:
            h = rows_h[key]
            if not first:
                hair = _rule(NSMakeRect(PAD, _y(t, 1), W - 2 * PAD, 1), HAIRLINE)
                content.addSubview_(hair); add(hair)
            first = False
            row = self._build_row(key, name, desc, action, style, NSMakeRect(PAD, _y(t, h), W - 2 * PAD, h))
            content.addSubview_(row); add(row)
            self._row_views[key] = row
            t += h

        foot = _label(NSMakeRect(PAD, 84, W - 2 * PAD, 32),
                      "Takes about 2 minutes. You can change any of this later "
                      "from the menu bar (🎙 icon).", _sf(12), INK_MUTED,
                      align=NSTextAlignmentCenter, multiline=True)
        content.addSubview_(foot); add(foot)

        self._done = _cta_button(NSMakeRect(PAD, 26, W - 2 * PAD, 48), "Continue →", self, "continue:")
        content.addSubview_(self._done); add(self._done)

    # ---------------- página 2: cómo dictar ----------------
    def _build_page2(self, content):
        add = self._page2.append

        hero = _keycap(NSMakeRect((W - 150) / 2, _y(56, 150), 150, 150), "⌘",
                       _serif(66), 28, gradient=True)
        content.addSubview_(hero); add(hero)

        title = _label(NSMakeRect(PAD, _y(232, 30), W - 2 * PAD, 30),
                       "You're ready to dictate", _serif(22, semibold=True), INK,
                       align=NSTextAlignmentCenter)
        content.addSubview_(title); add(title)
        sub = _label(NSMakeRect(PAD, _y(267, 20), W - 2 * PAD, 20),
                     "Two keys are all you need.", _sf(14), INK_SOFT,
                     align=NSTextAlignmentCenter)
        content.addSubview_(sub); add(sub)

        cap = _label(NSMakeRect(PAD, _y(309, 20), W - 2 * PAD, 20),
                     "Hold the RIGHT ⌘ key", _sf(14.5, 0.3), INK,
                     align=NSTextAlignmentCenter)
        content.addSubview_(cap); add(cap)
        instr = _label(NSMakeRect((W - 420) / 2, _y(335, 34), 420, 34),
                       "speak, then release — your words get typed where the cursor is.",
                       _sf(13), INK_SOFT, align=NSTextAlignmentCenter, multiline=True)
        content.addSubview_(instr); add(instr)

        t = 387
        first = True
        for keys, ttl, desc in (
            ("⌘ + Shift", "Hands-free", "Toggle dictation on/off without holding."),
            ("⌃⇧M", "Change mode", "Cycle 8 modes (verbatim, email, code…)."),
            ("Esc", "Cancel", "Throw away the dictation in progress."),
        ):
            hair = _rule(NSMakeRect(PAD, _y(t, 1), W - 2 * PAD, 1), HAIRLINE)
            content.addSubview_(hair); add(hair)
            first = False
            card = self._shortcut_row(NSMakeRect(PAD, _y(t + 1, 52), W - 2 * PAD, 52), keys, ttl, desc)
            content.addSubview_(card); add(card)
            t += 53

        # Cierra la lista y avisa de que nada de esto es definitivo. Va aquí y
        # no en un tooltip porque es la única pantalla que el usuario ve seguro:
        # sin este renglón, quien no puede usar la ⌘ derecha (teclado externo
        # sin ella, o la mano ocupada) se queda pensando que la app no es para
        # él, en vez de abrir Settings y cambiarla en dos clics.
        hair = _rule(NSMakeRect(PAD, _y(t, 1), W - 2 * PAD, 1), HAIRLINE)
        content.addSubview_(hair); add(hair)
        nota = _label(NSMakeRect(PAD, _y(t + 16, 34), W - 2 * PAD, 34),
                      "Prefer another key? Change it whenever you like from the "
                      "menu bar icon › Settings › Dictation key.",
                      _sf(12), INK_SOFT, align=NSTextAlignmentCenter, multiline=True)
        content.addSubview_(nota); add(nota)

        self._start = _cta_button(NSMakeRect(PAD, 26, W - 2 * PAD, 48), "Start dictating", self, "finish:")
        content.addSubview_(self._start); add(self._start)

    def _shortcut_row(self, frame, keys, title, desc):
        row = NSView.alloc().initWithFrame_(frame)
        rw = frame.size.width
        chip = _keycap(NSMakeRect(0, 8, 72, 36), keys, _sf(13, 0.3), 8)
        row.addSubview_(chip)
        row.addSubview_(_label(NSMakeRect(88, 27, rw - 88, 17), title, _sf(13.5, 0.3), INK))
        d = _label(NSMakeRect(88, 8, rw - 88, 17), desc, _sf(12.5), INK_SOFT)
        row.addSubview_(d)
        return row

    def _build_row(self, key, name, desc, action, style, frame):
        row = NSView.alloc().initWithFrame_(frame)
        rw, rh = frame.size.width, frame.size.height
        title_x = 34

        # punto de estado (● hecho / ○ pendiente) alineado con el título
        status = _label(NSMakeRect(0, rh - 29, 20, 20), "○", _sf(15), PENDING_RING,
                        align=NSTextAlignmentCenter)
        row.addSubview_(status)

        row.addSubview_(_label(NSMakeRect(title_x, rh - 27, 200, 16), name, _sf(14, 0.3), INK))
        if key == "ai":  # etiqueta "Optional" en gris junto al título
            row.addSubview_(_label(NSMakeRect(title_x + 78, rh - 26, 90, 15), "Optional",
                                   _sf(11.5), INK_MUTED))

        # Botón arriba, alineado con el título; la descripción va DEBAJO, a todo
        # el ancho (así no la recorta el botón — el bug que había).
        btn_w = {"Allow": 70, "Open Settings": 116, "Download": 104, "Connect AI": 100}.get(action, 100)
        btn = _row_button(NSMakeRect(rw - btn_w, rh - 31, btn_w, 24), action, style, self, f"{key}:")
        row.addSubview_(btn)

        full_w = rw - title_x - 8
        if key == "model":
            desc_lbl = _label(NSMakeRect(title_x, 20, full_w, 18), desc, _sf(12), INK_SOFT)
        elif key == "ai":
            desc_lbl = _label(NSMakeRect(title_x, 8, full_w, rh - 40), desc, _sf(12),
                              INK_SOFT, multiline=True)
        else:
            desc_lbl = _label(NSMakeRect(title_x, 8, full_w, 20), desc, _sf(12), INK_SOFT)
        row.addSubview_(desc_lbl)

        bar = None
        if key == "model":
            track_w = rw - title_x - 48
            bar = NSView.alloc().initWithFrame_(NSMakeRect(title_x, 6, track_w, 4))
            bar.setWantsLayer_(True)
            bar.layer().setBackgroundColor_(PROGRESS_TRACK.CGColor())
            bar.layer().setCornerRadius_(2.0)
            bar.setHidden_(True)
            try:
                from Quartz import CALayer
                fill = CALayer.layer()
                fill.setBackgroundColor_(TEAL.CGColor())
                fill.setCornerRadius_(2.0)
                fill.setFrame_(NSMakeRect(0, 0, 0, 4))
                bar.layer().addSublayer_(fill)
                self._model_fill = fill
                self._model_track_w = float(track_w)
            except Exception:
                log.debug("Sin CALayer para la barra de progreso", exc_info=True)
            row.addSubview_(bar)
            self._model_pct = _label(NSMakeRect(title_x + track_w + 6, 3, 36, 12), "",
                                     _mono(10.5, 0.3), BTN_GHOST_TEXT)
            self._model_pct.setHidden_(True)
            row.addSubview_(self._model_pct)

        self._rows[key] = {"status": status, "button": btn, "bar": bar}
        return row

    # ---------- acciones de los botones (selectores mic:, accessibility:, ...) ----------
    def _hide_for_settings(self):
        """Esconde el onboarding para que Ajustes del Sistema sea visible y
        manejable: si no, la ventana flotante se queda encima y lo bloquea. El
        NSTimer (_refresh) lo vuelve a mostrar cuando se concede el permiso o
        cuando el usuario vuelve a Voooxly."""
        self._win.orderOut_(None)
        self._hidden_for_settings = True
        self._hide_t = time.monotonic()

    def mic_(self, _sender):
        # requestAccess SOLO abre el prompt del sistema cuando el permiso está
        # "sin decidir". Si el usuario ya lo denegó una vez, macOS no vuelve a
        # preguntar y el botón parecería muerto: hay que llevarlo a Ajustes.
        status = setup_checks.microphone_status()
        log.info("Onboarding: clic en Microphone (status=%s)", status)
        if status == 0:  # notDetermined
            setup_checks.request_microphone()
        else:
            setup_checks.open_microphone_settings()
            self._hide_for_settings()

    def accessibility_(self, _sender):
        log.info("Onboarding: clic en Accessibility")
        setup_checks.open_accessibility_settings()
        self._hide_for_settings()

    def model_(self, _sender):
        if self._downloading:
            return
        self._downloading = True
        row = self._rows["model"]
        row["button"].setEnabled_(False)
        _set_button_title(row["button"], "Downloading…", TEAL_DARK)
        row["bar"].setHidden_(False)
        if self._model_pct is not None:
            self._model_pct.setHidden_(False)
        threading.Thread(target=self._download_model, daemon=True).start()

    def ai_(self, _sender):
        """Conectar IA: delega en el callback del app (selector de proveedor +
        key, flujo ya probado). Sin callback (test / standalone), re-detecta."""
        log.info("Onboarding: clic en Connect AI")
        if self._on_connect_ai is not None:
            try:
                self._on_connect_ai()
            except Exception:
                log.warning("Connect AI falló", exc_info=True)
            self._refresh()
        else:
            from . import refine
            refine.detect_backend(force=True)
            self._refresh()

    def continue_(self, _sender):
        """Página 1 → 2. Solo se habilita cuando los checks bloqueantes pasan."""
        self._show_page(2)

    def finish_(self, _sender):
        self._stop_timer()
        self._win.orderOut_(None)
        # Volvemos a app de barra: sin icono en el Dock ni menú principal. En el
        # arranque normal on_finish relanza un proceso nuevo (que ya nace
        # Accessory), pero en el fallback de dev seguimos vivos: hay que restaurar.
        try:
            NSApplication.sharedApplication().setActivationPolicy_(
                NSApplicationActivationPolicyAccessory)
        except Exception:
            log.debug("No pude restaurar la policy Accessory", exc_info=True)
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
            p = float(pct)
            if self._model_fill is not None:
                self._model_fill.setFrame_(NSMakeRect(0, 0, self._model_track_w * p / 100.0, 4))
            if self._model_pct is not None:
                self._model_pct.setStringValue_(f"{int(p)}%")
        except Exception:
            pass

    def downloadFinished_(self, _arg):
        row = self._rows["model"]
        _set_button_title(row["button"], "Download", TEAL_DARK)
        if self._model_pct is not None:
            self._model_pct.setHidden_(True)
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
            row["status"].setTextColor_(TEAL if check.ok else PENDING_RING)
            if not (check.key == "model" and self._downloading):
                row["button"].setEnabled_(not check.ok or check.key == "ai")
            # Cuando el requisito ya está, el botón sobra (el punto ● lo dice);
            # la IA queda siempre reconectable.
            row["button"].setHidden_(bool(check.ok) and check.key != "ai")
            if check.key == "model" and check.ok and row["bar"] is not None:
                row["bar"].setHidden_(True)
            if check.blocking and not check.ok:
                ready = False
        _style_cta(self._done, ready, "Continue →")

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
            self._step_label.setStringValue_("STEP 1 OF 2")
            self._done.setKeyEquivalent_("\r")
            self._start.setKeyEquivalent_("")
        else:
            self._step_label.setStringValue_("STEP 2 OF 2")
            self._done.setKeyEquivalent_("")
            self._start.setKeyEquivalent_("\r")

    def show(self):
        app = NSApplication.sharedApplication()
        # Promover a app de primer plano mientras dura el onboarding: así la
        # ventana se vuelve key/activa de verdad y los clics llegan a los botones
        # (en macOS 26, siendo accesoria, se los tragaba el window server). De
        # paso aparece tile en el Dock, que hace que minimizar tenga sentido.
        try:
            app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        except Exception:
            log.debug("No pude promover a Regular", exc_info=True)
        app.activateIgnoringOtherApps_(True)
        self._win.center()
        self._win.makeKeyAndOrderFront_(None)
        self._start_timer()
        # show() corre ANTES de que arranque el run loop de rumps, y activar antes
        # de tiempo no "pega". Re-activamos una vez el loop ya está vivo, y ~medio
        # segundo después registramos el estado YA asentado (comprobarlo en el
        # mismo tick del activate da un falso 'key=False' antes de que cuaje).
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.2, self, "reactivate:", None, False)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.7, self, "logState:", None, False)

    def reactivate_(self, _timer):
        try:
            app = NSApplication.sharedApplication()
            app.activateIgnoringOtherApps_(True)
            self._win.makeKeyAndOrderFront_(None)
        except Exception:
            log.debug("re-activación falló", exc_info=True)

    def logState_(self, _timer):
        try:
            app = NSApplication.sharedApplication()
            log.info("Onboarding activo: key=%s active=%s policy=%s",
                     self._win.isKeyWindow(), app.isActive(), app.activationPolicy())
        except Exception:
            pass


# ---------------- helpers de vistas ----------------
def _row_button(rect, title, style, target, action):
    """Botón de fila: 'ghost' (borde fino), 'tint' (relleno teal claro) o
    'text' (solo texto teal)."""
    b = NSButton.alloc().initWithFrame_(rect)
    b.setBordered_(False)
    b.setBezelStyle_(0)
    b.setWantsLayer_(True)
    b.layer().setCornerRadius_(8.0)
    b.setTarget_(target)
    b.setAction_(action)
    if style == "tint":
        b.layer().setBackgroundColor_(MODEL_BTN_BG.CGColor())
        b.layer().setBorderWidth_(1.0)
        b.layer().setBorderColor_(MODEL_BTN_BORDER.CGColor())
        fg = TEAL_DARK
    elif style == "text":
        fg = TEAL_DARK
    else:  # ghost
        b.layer().setBorderWidth_(1.0)
        b.layer().setBorderColor_(BTN_BORDER.CGColor())
        fg = BTN_GHOST_TEXT
    b.setTitle_(title)
    _set_button_title(b, title, fg)
    return b


def _set_button_title(b, title, fg):
    """Título de un botón de fila con color de marca (attributedTitle manda sobre
    setTitle_, así que los cambios de texto del modelo pasan por aquí)."""
    b.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(
        title, {NSFontAttributeName: _sf(12.5, 0.3), NSForegroundColorAttributeName: fg}))


def _cta_button(rect, title, target, action):
    """CTA principal, relleno teal, texto blanco."""
    b = NSButton.alloc().initWithFrame_(rect)
    b.setBordered_(False)
    b.setBezelStyle_(0)
    b.setWantsLayer_(True)
    b.layer().setCornerRadius_(10.0)
    b.setTarget_(target)
    b.setAction_(action)
    _style_cta(b, True, title)
    return b


def _style_cta(b, enabled, title):
    b.layer().setBackgroundColor_((TEAL if enabled else CTA_DISABLED_BG).CGColor())
    fg = NSColor.whiteColor() if enabled else CTA_DISABLED_TEXT
    b.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(
        title, {NSFontAttributeName: _sf(14, 0.3), NSForegroundColorAttributeName: fg}))
    b.setEnabled_(enabled)


# Referencia global: sin ella el recolector se lleva la ventana y desaparece sola.
_controller = None


def show_onboarding(on_finish=None, on_connect_ai=None) -> None:
    """Muestra el asistente. DEBE llamarse desde el hilo principal."""
    global _controller
    try:
        _controller = OnboardingController.alloc().initWithFinish_connectAI_(
            on_finish, on_connect_ai)
        _controller.show()
    except Exception as e:
        log.error("No pude mostrar el onboarding: %s", e)
