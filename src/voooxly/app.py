"""App de barra de menús (rumps) que orquesta todo el sistema de dictado.

Máquina de estados simple:
  IDLE -> (toggle) -> RECORDING -> (toggle | silencio) -> PROCESSING -> IDLE

Durante RECORDING se muestra el overlay con transcripción parcial.
Al finalizar: STT final -> refino por modo -> entregar (clipboard + paste).
"""
from __future__ import annotations

import collections
import json
import logging
import os
import plistlib
import subprocess
import threading
import time

import rumps

from . import audio, dictionary, history, keys, media, modes, output, providers, refine, richtext, setup_checks, stats, stt, updates
from .config import get_config, resolve_language
from .hotkey import HotkeyManager
from .overlay import Overlay

log = logging.getLogger("voooxly")

# Preferencias que se tocan desde el menú (el config.yaml va DENTRO del .app y
# es de solo lectura en la práctica): un json pequeño en ~/.voooxly.
PREFS_PATH = os.path.expanduser("~/.voooxly/prefs.json")
# "Start at login": un LaunchAgent clásico — sin APIs de ServiceManagement,
# funciona igual lanzado desde el repo o desde /Applications.
LAUNCH_AGENT = os.path.expanduser(
    "~/Library/LaunchAgents/com.eduardocrovetto.voooxly.plist"
)
HISTORY_SIZE = 10


def _load_prefs() -> dict:
    try:
        with open(PREFS_PATH) as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_prefs(prefs: dict) -> None:
    try:
        os.makedirs(os.path.dirname(PREFS_PATH), exist_ok=True)
        with open(PREFS_PATH, "w") as f:
            json.dump(prefs, f, indent=2)
    except Exception:
        log.warning("No pude guardar prefs en %s", PREFS_PATH)


def ai_menu_labels(selection) -> list[tuple[str, bool]]:
    """Filas del submenú AI engine: (etiqueta, ¿es el activo?).

    A nivel de módulo y no como método para poder testearla: instanciar
    VoooxlyApp construye menús de AppKit y eso no corre en un test.
    """
    filas = []
    for prov in providers.PROVIDERS.values():
        # Etiqueta limpia, sin "…": la lista corta ya se entiende y el "…" en
        # cada fila se veía ruidoso. Al pulsar se pide la key (o el modelo de
        # Ollama), pero eso no justifica ensuciar las cinco filas.
        etiqueta = prov.label
        activo = selection is not None and selection.provider.key == prov.key
        filas.append((etiqueta, activo))
    return filas


# Nombres cortos para los backends que devuelve refine.detect_backend(): las
# filas del submenú "AI engine" ya no pueden mostrarlos (solo llevan check),
# así que este título compensa vía el padre del submenú, que sí admite texto.
_BACKEND_LABELS = {"ollama": "Ollama", "claude": "Claude", "openai": "OpenAI"}


def ai_engine_title(selection, detected: str) -> str:
    """Título del ítem padre del submenú AI engine: la única pista visible de
    qué motor está activo (las filas hijas solo llevan un check).

    A nivel de módulo y no como método, por el mismo motivo que
    ai_menu_labels: instanciar VoooxlyApp construye menús de AppKit.
    """
    if selection is not None:
        # .name, no .label: label lleva la nota ("Groq — free") y saldría
        # "AI engine — Groq — free", con dos guiones largos seguidos.
        return f"AI engine — {selection.provider.name}"
    if detected == "none":
        return "AI engine — none (raw text)"
    label = _BACKEND_LABELS.get(detected, detected)
    return f"AI engine — {label} (auto)"


def check_now_message(status: str, info: dict | None, local: str) -> tuple[str, str]:
    """(title, message) para el resultado de un 'Check for updates…' manual.

    Pure: el cableado UI la llama desde _check_now y le pasa lo que devolvió
    updates.check_status(). Sin info -> error o al día según status.
    """
    if status == updates.UPDATE_AVAILABLE and info:
        ver = info["version"]
        notes = (info.get("notes") or "").strip()
        body = f"Voooxly {ver} is available." + (f"\n\n{notes}" if notes else "")
        return "Update available", body
    if status == updates.UP_TO_DATE:
        return "Up to date", f"You're running the latest version (Voooxly {local})."
    return "Couldn't check", "Couldn't reach the update server. Try again later."


def apply_ai_selection(cfg, sel) -> None:
    """Aplica la elección al config VIVO (aquí sí toca: es configurar la app).

    A nivel de módulo y no como método para poder testearla sin instanciar
    VoooxlyApp (mismo motivo que ai_menu_labels/ai_engine_title: AppKit no
    corre en pytest).

    A diferencia de _probe(), que no debe tocar el singleton, este ES el
    momento de escribirlo: el usuario acaba de elegir. La ruta depende del
    kind — mismo branching que _probe y por el mismo motivo (los presets
    OpenAI-compatibles comparten llm.openai.*).
    """
    if sel is None:
        return
    cfg._set_path("llm.backend", sel.provider.kind)
    cfg._set_path(f"llm.{sel.provider.kind}.model", sel.model)
    if sel.provider.kind == "ollama":
        cfg._set_path("llm.ollama.host", sel.base_url)
    elif sel.base_url:
        # Claude no tiene base_url propia (el SDK de anthropic gestiona su
        # endpoint solo, base_url == "" por diseño en providers.py): escribir
        # aquí incondicionalmente dejaba llm.openai.base_url = "" en vivo cada
        # vez que se conectaba o restauraba Claude, rompiendo la ruta
        # OpenAI-compatible hasta el próximo proveedor openai-kind conectado.
        cfg._set_path("llm.openai.base_url", sel.base_url)


def _record_token_usage(refiner, prefs) -> None:
    """Cuenta los tokens del último refino remoto, si los hubo.

    A nivel de módulo (mismo motivo que apply_ai_selection: poder testear sin
    instanciar VoooxlyApp) y porque _process la llama DESPUÉS de
    output.deliver() a propósito: contar tokens es puro best-effort para que
    quien use un free tier vea cuánto lleva gastado, y NUNCA puede impedir ni
    preceder el pegado. Antes, ai_settings.load(self._prefs) corría dentro
    del try/except de _process y ANTES de deliver(); si lanzaba (un
    prefs.json corrupto, por ejemplo), _process abortaba al catch-all y el
    texto ya refinado no llegaba a pegarse — perder el dictado del usuario
    por un fallo al contar tokens es el peor desenlace posible aquí.
    """
    try:
        usados = getattr(refiner, "last_usage", None)
        if not usados:
            return
        from . import ai_settings

        sel = ai_settings.load(prefs)
        stats.bump_tokens(usados, sel.provider.name if sel else "")
    except Exception:
        log.debug("No pude contar tokens tras el pegado", exc_info=True)


class VoooxlyApp(rumps.App):
    def __init__(self):
        cfg = get_config()
        self.cfg = cfg
        self.mode = cfg.get("app.default_mode", "ordenar")
        # "auto" -> idioma del sistema de quien use la app, no el del autor.
        self.language = resolve_language(cfg.get("app.language", None))
        self.stt_model = cfg.get("stt.model")
        self.stt_lang = resolve_language(cfg.get("stt.language", None))
        self._state = "IDLE"
        self._lock = threading.Lock()
        # Esc durante grabación/procesado: descartar el dictado sin pegar nada.
        self._cancel = threading.Event()
        self._recorder: audio.Recorder | None = None
        self._overlay = Overlay(cfg.get("app.overlay_position", "bottom-right"))
        self._last_result = ""
        self._show_overlay = bool(cfg.get("app.show_overlay", True))
        self._partial_thread: threading.Thread | None = None
        self._partial_running = threading.Event()
        self._prefs = _load_prefs()
        self._sounds = bool(self._prefs.get("sounds", cfg.get("app.sounds", True)))
        self._snd_cache: dict = {}   # NSSound vivos mientras suenan (si no, dealloc a mitad)
        self._history: collections.deque[str] = collections.deque(maxlen=HISTORY_SIZE)
        # Diccionario (config + personal) → initial prompt de Whisper (sesga
        # hacia esas grafías). Whisper solo usa ~224 tokens: se recorta.
        self.stt_prompt = self._build_stt_prompt()

        icon_path = self._asset("menubar.png")
        self._has_icon = icon_path is not None
        self._idle_icon = icon_path
        self._rec_icon = self._asset("menubar-rec.png")
        self._rec_shown = False
        self._timer_seq = 0
        super().__init__(
            name="Voooxly",
            icon=icon_path,          # glyph template (se adapta a claro/oscuro)
            title=None if self._has_icon else "🎙",
            template=True,
            quit_button=None,        # rumps añade un "Quit" propio si no se anula
        )                            # (usamos el nuestro, que apaga server/hotkey)
        # Se resuelve ANTES de _build_menu(): el submenú de tecla/estilo marca
        # el check inicial leyendo self._dictation_key/self._toggle_mode, así
        # que tienen que existir antes de construir esos NSMenuItem.
        tecla, modo, guarda = keys.resolve(self._prefs, cfg)
        self._toggle_mode = modo
        self._dictation_key = tecla
        self._build_menu()
        self._apply_login_default()
        self._hotkey = HotkeyManager(
            toggle_mode=modo,
            toggle_keys=[tecla],
            cycle_keys=cfg.get("hotkeys.cycle_mode", ["ctrl", "shift", "m"]),
            paste_keys=cfg.get("hotkeys.paste_last", ["ctrl", "shift", "v"]),
            on_toggle=self.toggle_record,
            on_start=self.start_record,
            on_stop=self.stop_record,
            on_cycle=self.cycle_mode,
            on_paste=self.paste_last,
            cancel_keys=cfg.get("hotkeys.cancel", ["esc"]),
            on_cancel=self.cancel_record,
            latch_keys=cfg.get("hotkeys.latch", ["shift"]),
            on_latch=self._on_latch,
            toggle_guard=guarda,
        )

    def _on_latch(self):
        log.info("Latch: grabación fijada, tap en la tecla de dictado para terminar.")
        try:
            self._overlay.update("🔒 Hands-free — tap the dictation key to finish")
        except Exception:
            pass

    @staticmethod
    def _asset(name: str) -> str | None:
        import os
        import sys

        cands = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            cands.append(os.path.join(meipass, "assets", name))
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cands.append(os.path.join(repo, "assets", name))
        for c in cands:
            if os.path.exists(c):
                return c
        return None

    # ---------- menú ----------
    def _build_menu(self):
        items = []
        for key, info in modes.modes_by_key().items():
            mi = rumps.MenuItem(info["label"], callback=self._make_mode_cb(key))
            mi.state = 1 if key == self.mode else 0
            items.append(mi)
        self.mode_items = {key: mi for (key, _), mi in zip(modes.modes_by_key().items(), items)}

        self.status = rumps.MenuItem("Ready", callback=None)
        self.ai = rumps.MenuItem("AI engine")
        self._ai_items = {}
        for prov_key, (etiqueta, _) in zip(providers.PROVIDERS, ai_menu_labels(None)):
            mi = rumps.MenuItem(etiqueta, callback=self._make_provider_cb(prov_key))
            self.ai.add(mi)
            self._ai_items[prov_key] = mi
        self.ai.add(rumps.separator)
        self.ai_auto_item = rumps.MenuItem("Detect automatically", callback=self._reset_to_auto)
        self.ai.add(self.ai_auto_item)
        self.ai_test_item = rumps.MenuItem("Test connection", callback=self._test_ai)
        self.ai.add(self.ai_test_item)
        self.stats_item = rumps.MenuItem("Usage stats…", callback=self._show_stats)
        self.quit = rumps.MenuItem("Quit Voooxly", callback=self._quit)
        # Oculto hasta que el comprobador encuentre una versión nueva (ver _warmup).
        self.update_item = rumps.MenuItem("Update available", callback=self._open_update)
        self.about_item = rumps.MenuItem("About Voooxly", callback=self._show_about)
        self._update_url = ""
        self._update_version = ""
        self._update_downloading = False
        # Re-chequeo periódico cada updates.CHECK_INTERVAL; HUD una vez por versión.
        self._update_timer: threading.Timer | None = None
        self._notified_update_version: str | None = None
        self._paused_players: list[str] = []
        self._mode_flash_seq = 0
        self._mic_warned = False

        # Recent: los últimos dictados, clic = volver a copiarlos al portapapeles.
        # Los items se PRE-crean ocultos: añadir/quitar items de un NSMenu desde el
        # hilo de proceso sería inseguro; cambiar título/hidden funciona bien.
        self.recent_parent = rumps.MenuItem("Recent")
        self._recent_empty = rumps.MenuItem("(empty)")
        self.recent_parent.add(self._recent_empty)
        self._recent_items: list[rumps.MenuItem] = []
        for i in range(HISTORY_SIZE):
            mi = rumps.MenuItem(f"recent-{i}", callback=self._make_recent_cb(i))
            self.recent_parent.add(mi)
            mi._menuitem.setHidden_(True)
            self._recent_items.append(mi)

        settings = rumps.MenuItem("Settings")
        self.login_item = rumps.MenuItem("Start at login", callback=self._toggle_login)
        self.login_item.state = 1 if os.path.exists(LAUNCH_AGENT) else 0
        self.sounds_item = rumps.MenuItem("Sounds", callback=self._toggle_sounds)
        self.sounds_item.state = 1 if self._sounds else 0
        self.dict_item = rumps.MenuItem("Add to dictionary…", callback=self._add_to_dictionary)
        settings.add(self.login_item)
        settings.add(self.sounds_item)
        settings.add(self.dict_item)

        # Tecla de dictado: la que va bien depende de cada teclado y de qué
        # más use el usuario. Sin esto solo se cambia editando config.yaml.
        self.key_parent = rumps.MenuItem("Dictation key")
        self.key_items: dict[str, rumps.MenuItem] = {}
        for k, dk in keys.DICTATION_KEYS.items():
            mi = rumps.MenuItem(dk.label, callback=self._make_key_cb(k))
            mi.state = 1 if k == self._dictation_key else 0
            self.key_parent.add(mi)
            self.key_items[k] = mi
        self.key_parent.add(rumps.separator)

        self.style_parent = rumps.MenuItem("Dictation style")
        self.style_items: dict[str, rumps.MenuItem] = {}
        for m, label in keys.MODES.items():
            mi = rumps.MenuItem(label, callback=self._make_style_cb(m))
            mi.state = 1 if m == self._toggle_mode else 0
            self.style_parent.add(mi)
            self.style_items[m] = mi

        settings.add(self.key_parent)
        settings.add(self.style_parent)

        self.search_item = rumps.MenuItem("Search history…", callback=self._search_history)

        self.menu = [
            *items,
            rumps.separator,
            self.recent_parent,
            self.search_item,
            rumps.separator,
            self.status,
            self.ai,
            self.stats_item,
            settings,
            rumps.separator,
            self.about_item,
            self.update_item,
            self.quit,
        ]
        # setHidden_ debe ir DESPUÉS de asignar self.menu: hasta entonces rumps no
        # ha creado el NSMenuItem real y el ocultado se pierde.
        self.update_item._menuitem.setHidden_(True)
        self._refresh_title()

    def _make_mode_cb(self, key):
        def cb(_sender):
            self.set_mode(key)
        return cb

    def set_mode(self, key: str):
        if key not in modes.MODES:
            return
        self.mode = key
        # mi.state es AppKit sobre NSMenuItem; set_mode se llama también desde el
        # hotkey Ctrl+Shift+M (hilo de fondo), no solo desde el menú → va por el
        # main o crashea con el menú abierto (mismo SIGTRAP que _refresh_title).
        def apply():
            for k, mi in self.mode_items.items():
                mi.state = 1 if k == key else 0
        self._on_main(apply)
        self._refresh_title()
        log.info("Modo: %s", modes.MODES[key]["label"])
        self._flash_mode()

    def _flash_mode(self):
        """Flash del HUD con el modo recién activado (nombre + posición + hint).

        Sin esto, ciclar con Ctrl+Shift+M es a ciegas: 8 modos y ninguna pista
        de en cuál has caído. Se auto-oculta a los ~1.4s; ciclar rápido solo
        renueva el timer (el seq más nuevo manda) y un dictado en curso tiene
        prioridad sobre el flash.
        """
        if not self._show_overlay or not getattr(self._overlay, "_built", False):
            log.debug(
                "flash: descartado (show_overlay=%s, built=%s)",
                self._show_overlay, getattr(self._overlay, "_built", None),
            )
            return
        with self._lock:
            if self._state != "IDLE":
                return  # el HUD está ocupado con un dictado
        self._mode_flash_seq += 1
        seq = self._mode_flash_seq

        def _do():
            try:
                title, body = modes.flash_parts(self.mode)
                self._overlay.show(body, title=title)
                time.sleep(1.4)
                if self._mode_flash_seq != seq:
                    return  # hubo otro cambio de modo: su flash manda
                with self._lock:
                    if self._state != "IDLE":
                        return  # empezó un dictado: su flujo gestiona el HUD
                self._overlay.hide()
            except Exception:
                log.warning("Flash de modo falló", exc_info=True)

        threading.Thread(target=_do, daemon=True).start()

    def cycle_mode(self):
        keys = list(modes.MODES.keys())
        try:
            i = keys.index(self.mode)
        except ValueError:
            i = -1
        self.set_mode(keys[(i + 1) % len(keys)])

    def _on_main(self, fn):
        """Ejecuta fn en el hilo principal. AppKit NO es thread-safe: escribir
        el título de la barra o de un NSMenuItem desde un hilo de grabación/
        proceso mientras un menú está ABIERTO reflowa la ventana del popup desde
        el hilo equivocado y aborta con SIGTRAP (EXC_BREAKPOINT). Todo write de
        .title pasa por aquí. Si un menú está abierto el runloop está en
        tracking y el update se aplica al cerrarlo: se ve con un instante de
        retraso, pero nunca crashea."""
        if threading.current_thread() is threading.main_thread():
            try:
                fn()
            except Exception:
                log.debug("update de título falló", exc_info=True)
            return
        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(fn)
        except Exception:
            log.debug("no pude encolar update de título en el main thread", exc_info=True)

    def _refresh_title(self):
        label = modes.MODES.get(self.mode, {}).get("label", "Voooxly")
        state = self._state
        # Barra de menú: glyph template en reposo; grabando = punto rojo +
        # cronómetro (lo lleva _rec_timer); procesando = glyph + "…".
        if state == "RECORDING" and self._rec_icon:
            self._swap_icon(rec=True)
            set_bar = False   # el cronómetro (_start_rec_timer) es dueño del título
        else:
            self._swap_icon(rec=False)
            set_bar = True
        bar = {"RECORDING": "🔴", "PROCESSING": "…"}.get(
            state, None if self._has_icon else "🎙"
        )
        state_en = {"IDLE": "ready", "RECORDING": "recording", "PROCESSING": "processing"}
        status = f"Mode: {label} · {state_en.get(state, state)}"

        # AppKit desde el hilo de grabación mata la app con el menú abierto: se
        # marshala. El icono ya lo hacía (_swap_icon); los títulos NO — ese era
        # el bug del SIGTRAP a los 60s con el menú desplegado.
        def apply():
            if set_bar:
                self.title = bar
            self.status.title = status

        self._on_main(apply)

    def _swap_icon(self, rec: bool):
        """Cambia el icono de la barra en el main thread (AppKit no es
        thread-safe y _refresh_title llega desde hilos de grabación)."""
        if not self._has_icon or rec == self._rec_shown or (rec and not self._rec_icon):
            return
        self._rec_shown = rec

        def apply():
            try:
                self.template = not rec
                self.icon = self._rec_icon if rec else self._idle_icon
            except Exception:
                log.debug("No pude cambiar el icono de la barra", exc_info=True)

        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(apply)
        except Exception:
            apply()

    def _start_rec_timer(self):
        """Cronómetro 0:07 junto al punto rojo mientras se graba."""
        self._timer_seq += 1
        seq = self._timer_seq
        t0 = time.monotonic()

        def run():
            while self._timer_seq == seq:
                with self._lock:
                    if self._state != "RECORDING":
                        break
                s = int(time.monotonic() - t0)
                txt = f" {s // 60}:{s % 60:02d}"
                # Este hilo escribía self.title directo: AppKit desde hilo de
                # fondo. Marshalado al main como el resto (ver _on_main).
                self._on_main(lambda txt=txt: setattr(self, "title", txt))
                time.sleep(1.0)

        threading.Thread(target=run, daemon=True).start()

    # ---------- grabación ----------
    def toggle_record(self):
        with self._lock:
            state = self._state
        if state == "IDLE":
            self._start_record(auto_stop=True)
        elif state == "RECORDING":
            self._stop_record(force=True)

    def start_record(self):
        """Push-to-talk: tecla pulsada -> empieza a grabar (si está IDLE)."""
        with self._lock:
            if self._state != "IDLE":
                return
        try:
            self._start_record(auto_stop=False)
        except Exception:
            log.exception("Error en start_record (se resetea a IDLE)")
            with self._lock:
                self._state = "IDLE"
            self._refresh_title()

    def stop_record(self):
        """Push-to-talk: tecla soltada -> termina la grabación."""
        with self._lock:
            if self._state != "RECORDING":
                return
        try:
            self._stop_record(force=True)
        except Exception:
            log.exception("Error en stop_record")

    def cancel_record(self):
        """Esc: descarta el dictado en curso (grabando o procesando). No pega nada.

        Se dispara con CADA Esc del sistema, así que el no-op cuando está IDLE
        tiene que ser inmediato y sin efectos.
        """
        with self._lock:
            state = self._state
            if state == "IDLE":
                return
            self._cancel.set()
        log.info("Dictado cancelado por el usuario (estado %s).", state)
        if state == "RECORDING":
            try:
                self._stop_record(force=True)  # dispara _on_stop, que verá _cancel
            except Exception:
                log.exception("Error cancelando la grabación")

    def _start_record(self, auto_stop: bool = True):
        self._cancel.clear()
        with self._lock:
            self._state = "RECORDING"
        self._refresh_title()
        # Push-to-talk (auto_stop=False): el usuario controla el fin con la tecla,
        # desactivamos el auto-stop por silencio para que no cierre al pausar a pensar.
        # Menú/toggle (auto_stop=True): la grabación se cierra sola tras el silencio.
        silence = self.cfg.get("audio.silence_to_stop", 1.2)
        if not auto_stop:
            silence = 9999.0
        acfg = audio.AudioConfig(
            device=self.cfg.get("audio.device"),
            vad_aggressiveness=self.cfg.get("audio.vad_aggressiveness", 2),
            silence_to_stop=silence,
            max_duration=self.cfg.get("audio.max_duration", 300.0),
            min_duration=self.cfg.get("audio.min_duration", 0.4),
        )
        self._recorder = audio.Recorder(acfg)
        if self._show_overlay:
            self._overlay.show("Speak now.", title="● Listening")
        # hilo de partials: re-transcribe la ventana reciente
        self._partial_running.set()
        self._partial_thread = threading.Thread(target=self._partial_loop, daemon=True)
        self._partial_thread.start()
        self._recorder.start(on_stop=self._on_stop)
        self._start_rec_timer()
        self._play_sound("Pop")     # "te escucho"
        # Pausar la música (Spotify/Music) mientras dictas. En hilo aparte:
        # osascript tarda 100-300ms y no debe retrasar la captura del micro.
        if self.cfg.get("audio.pause_media", True):
            threading.Thread(target=self._pause_media, daemon=True).start()
        log.info("Grabando…")

    def _pause_media(self):
        try:
            self._paused_players = media.pause_playing()
        except Exception:
            self._paused_players = []
        # Pulsación ultracorta: si el dictado terminó mientras pausábamos,
        # _on_stop ya pasó y nadie más va a reanudar. Hazlo aquí.
        with self._lock:
            recording = self._state == "RECORDING"
        if not recording:
            self._resume_media()

    def _resume_media(self):
        players, self._paused_players = self._paused_players, []
        if players:
            threading.Thread(target=media.resume, args=(players,), daemon=True).start()

    def _stop_record(self, force: bool):
        if self._recorder:
            if force:
                self._recorder.force_finish()
            else:
                self._recorder.stop()

    def _partial_loop(self):
        interval = self.cfg.get("stt.partial_interval", 1.5)
        while self._partial_running.is_set():
            time.sleep(interval)
            if not self._partial_running.is_set() or self._recorder is None:
                break
            try:
                a = self._recorder.get_recent_audio()
                # sin señal suficiente no se transcribe: Whisper alucina con silencio
                if len(a) / audio.SR < 0.4 or audio.rms_of(a) < self._min_rms():
                    continue
                text = stt.transcribe(a, self.stt_model, self._stt_language(), self.stt_prompt)
                if text and self._partial_running.is_set():
                    self._overlay.update(text)
            except Exception as e:
                log.debug("partial error: %s", e)

    def _min_rms(self) -> float:
        return float(self.cfg.get("audio.min_rms", 50))

    def _stt_language(self) -> str | None:
        """Idioma efectivo para el STT: el modo puede forzar el suyo
        (p.ej. Traducir EN→ES dicta en inglés)."""
        return modes.MODES.get(self.mode, {}).get("stt_lang") or self.stt_lang

    def _on_stop(self, audio_buf, duration: float):
        self._partial_running.clear()
        # La música vuelve en cuanto el micro se cierra: el refino puede seguir
        # unos segundos, pero el usuario ya no está hablando.
        self._resume_media()
        if self._cancel.is_set():
            threading.Thread(target=self._finish_cancel, daemon=True).start()
            return
        self._play_sound("Tink")    # "recibido, procesando"
        rec = self._recorder
        had_speech = rec.had_speech if rec else False
        speech_ratio = rec.speech_ratio if rec else 0.0
        with self._lock:
            self._state = "PROCESSING"
        self._refresh_title()
        self._overlay.show("Transcribing…", title="✦ Processing")
        threading.Thread(
            target=self._process,
            args=(audio_buf, duration, had_speech, speech_ratio),
            daemon=True,
        ).start()

    def _flash(self, msg: str, secs: float = 1.6, title: str | None = None):
        """Mensaje breve en el HUD (el finally de _process lo cierra después)."""
        try:
            self._overlay.show(msg, title=title)
            time.sleep(secs)
        except Exception:
            pass

    # ---------- avisos al usuario ----------
    # rumps.notification (NSUserNotification) NO entrega nada en macOS 26: la app
    # ni siquiera llega a registrarse en el Centro de Notificaciones y los avisos
    # se descartan en silencio. Todo aviso sale por uno de estos dos caminos,
    # ambos verificados con screencapture/CGWindowList:
    #   _alert() → NSAlert modal, para info que el usuario ha pedido y quiere leer.
    #   _hud()   → HUD efímero, para eventos de fondo que NO deben robar el foco.

    def _alert(self, title: str, message: str = ""):
        """Modal para info pedida por el usuario. No bloquea al que llama."""

        def show():
            try:
                rumps.alert(title=title, message=message, ok="OK")
            except Exception:
                log.warning("No pude mostrar el alert %r", title, exc_info=True)

        # NSAlert solo puede correr en el main thread; los callbacks de menú ya
        # están en él, pero _warmup y las descargas llegan desde hilos daemon.
        if threading.current_thread() is threading.main_thread():
            show()
        else:
            try:
                from PyObjCTools import AppHelper

                AppHelper.callAfter(show)
            except Exception:
                log.warning("No pude encolar el alert %r", title, exc_info=True)

    def _hud(self, msg: str, title: str | None = None, secs: float = 2.0):
        """Aviso efímero en el HUD, sin bloquear ni robar el foco.

        Comparte contador con el flash de modo: el mensaje más nuevo manda y un
        dictado en curso tiene prioridad (su flujo gestiona el HUD).
        """
        if not self._show_overlay or not getattr(self._overlay, "_built", False):
            log.info("HUD no disponible, aviso solo al log: %s — %s", title or "", msg)
            return
        self._mode_flash_seq += 1
        seq = self._mode_flash_seq

        def _do():
            try:
                with self._lock:
                    if self._state != "IDLE":
                        return
                self._overlay.show(msg, title=title)
                time.sleep(secs)
                if self._mode_flash_seq != seq:
                    return  # llegó un aviso más nuevo: manda el suyo
                with self._lock:
                    if self._state != "IDLE":
                        return  # empezó un dictado
                self._overlay.hide()
            except Exception:
                log.warning("Aviso en el HUD falló", exc_info=True)

        threading.Thread(target=_do, daemon=True).start()

    def _finish_cancel(self):
        """Cierre visual de un dictado cancelado con Esc."""
        self._play_sound("Basso")
        self._flash("(canceled — nothing pasted)", 0.9)
        self._reset_idle()

    def _process(self, audio_buf, duration, had_speech: bool = True, speech_ratio: float = 0.0):
        t0 = time.monotonic()
        try:
            if audio_buf is None or len(audio_buf) == 0:
                log.info("Grabación descartada (muy corta).")
                self._flash("(too short)", 1.0)
                return
            # 0) guardas: nunca mandar silencio a Whisper (alucina "Gracias"/"Thank you").
            # Dos silencios distintos: RMS≈0 es silencio DIGITAL (permiso TCC
            # denegado o micro muteado — hay que avisar, pero solo una vez por
            # sesión); RMS bajo pero no nulo es una sala tranquila con alguien
            # que no habló — descarte discreto sin notificación del sistema.
            level = audio.rms_of(audio_buf)
            if level < self._min_rms():
                if level < 3.0 and not self._mic_warned:
                    self._mic_warned = True
                    log.warning(
                        "Micrófono sin señal (RMS=%.0f). ¿Permiso de Micrófono concedido?", level
                    )
                    self._flash("🎤 No signal from the microphone", 2.5)
                else:
                    log.info("Descartado: sin voz (RMS=%.0f).", level)
                    self._flash("(no speech — nothing pasted)", 1.2)
                return
            self._mic_warned = False  # audio sano: si el micro muere luego, re-avisar
            if not had_speech:
                log.info("Sin voz detectada por VAD (RMS=%.0f).", level)
                self._flash("(no speech detected)", 1.2)
                return
            # 1) transcripción final
            transcript = stt.transcribe(
                audio_buf, self.stt_model, self._stt_language(), self.stt_prompt
            )
            log.info(
                "Transcripción (%.1fs, RMS=%.0f, voz=%.0f%%): %s",
                duration, level, speech_ratio * 100, transcript,
            )
            if self._cancel.is_set():
                log.info("Cancelado tras la transcripción; nada pegado.")
                self._flash("(canceled — nothing pasted)", 0.9)
                return
            if not transcript:
                # Distinguir "no dijiste nada" de "el motor STT está caído":
                # con voz detectada por el VAD y el server sin responder, el
                # problema es del motor y reintentar en unos segundos funciona.
                if had_speech and not stt.server_ready():
                    log.warning("STT sin transcripción con voz detectada: server caído.")
                    self._flash("⚠️ Speech engine restarting — try again in a moment", 2.2)
                else:
                    self._flash("(no speech detected)", 1.2)
                return
            if stt.looks_hallucinated(transcript, speech_ratio):
                log.warning("Descartada como alucinación de Whisper: %r", transcript)
                self._flash("(didn't catch that — say it again)", 1.5)
                return
            # Enseñar ya lo transcrito: la espera del refino (2-6s) se entiende
            # mejor viendo el texto que con un "Processing…" opaco.
            self._overlay.show(transcript, title="✦ Polishing")
            # 2) refino por modo (si falla, cae a la transcripción cruda: nunca bloquea)
            # Fast-lane: dictados cortos en modos marcados se pegan tal cual —
            # Whisper ya puntúa bien frases breves y ahorramos 2-6s de LLM.
            fast_words = int(self.cfg.get("llm.fast_lane_words", 9))
            n_words = len(transcript.split())
            # refiner sólo se instancia en la rama que de verdad llama a refine():
            # el aviso de más abajo lo consulta con getattr(refiner, ...), así
            # que en fast-lane (refiner=None) simplemente no dispara — nunca un
            # flag rancio de un dictado anterior.
            refiner = None
            # Igual que refiner=None: sólo se pone a True dentro de la rama
            # que de verdad llama a refine(), así que en fast-lane queda
            # inerte (nunca un aviso de un dictado anterior).
            refine_crashed = False
            if (
                fast_words > 0
                and modes.MODES.get(self.mode, {}).get("fast_lane")
                and n_words <= fast_words
            ):
                log.info("Fast-lane (%d palabras): sin refino LLM.", n_words)
                final = transcript
            else:
                refiner = refine.Refiner(self.cfg)
                try:
                    final = refiner.refine(transcript, self.mode, self.language)
                except Exception:
                    log.exception("Refinado falló; uso transcripción cruda")
                    final = transcript
                    # Red de seguridad: un bug de refino no pierde el dictado
                    # (se pega crudo), pero eso NO puede pasar en silencio —
                    # el usuario tiene que enterarse igual que con last_fallback.
                    refine_crashed = True
            final = final or transcript
            # Reemplazos del diccionario personal: corrección determinista de
            # las grafías que Whisper sigue fallando aunque estén en el prompt.
            try:
                final = dictionary.apply(final)
            except Exception:
                log.debug("dictionary.apply falló; sigo sin reemplazos", exc_info=True)
            if self._cancel.is_set():
                log.info("Cancelado durante el refino; nada pegado.")
                self._flash("(canceled — nothing pasted)", 0.9)
                return
            self._last_result = final
            self._push_history(final)
            stats.bump(len(final.split()), duration)
            log.info("Final (+%.1fs): %s", time.monotonic() - t0, final)
            # 3) entregar
            auto_paste = bool(self.cfg.get("output.auto_paste", True))
            copy = bool(self.cfg.get("output.copy_to_clipboard", True))
            # Modos con estructura Markdown: segundo sabor HTML en el
            # portapapeles para que Mail/Gmail/Notion peguen títulos y
            # listas renderizados (las apps de texto plano ni lo ven).
            html = None
            if modes.MODES.get(self.mode, {}).get("rich_paste"):
                try:
                    html = richtext.markdown_to_html(final)
                except Exception:
                    log.debug("markdown_to_html falló; pego solo texto plano", exc_info=True)
            status = output.deliver(final, auto_paste=auto_paste, copy=copy, html=html)
            # Tokens del LLM remoto, si lo hubo — SIEMPRE después de entregar:
            # nada en este camino puede impedir ni preceder el pegado (ver
            # _record_token_usage). getattr porque en fast-lane refiner es
            # None — el mismo patrón que el aviso de last_fallback más abajo.
            _record_token_usage(refiner, self._prefs)
            # El texto ya se pegó (con o sin refino): este aviso solo informa
            # que la IA no actuó y se pegó la transcripción cruda por un fallo
            # (red caída, proveedor roto..., o el catch-all de arriba si
            # refine() lanzó algo que ni siquiera Refiner supo manejar). Los
            # caminos deliberados (modo literal, fast-lane, backend "none")
            # no dejan ni last_fallback ni refine_crashed puestos.
            if refine_crashed or getattr(refiner, "last_fallback", None):
                self._flash(
                    "Your words were pasted as-is.", 2.2,
                    title="⚠ AI didn't answer",
                )
            if auto_paste and status == "copied":
                # El pegado falló pero el texto SÍ está en el portapapeles:
                # sin este aviso el usuario ve que "no pasa nada" y lo pierde.
                self._flash("Press ⌘V to paste it where you need it.", 2.2, title="✓ Copied")
            else:
                # mostrar resultado breve y cerrar
                self._overlay.show(final, title="✓ Pasted")
                time.sleep(1.6)
        except Exception:
            log.exception("Error procesando dictado")
        finally:
            self._reset_idle()

    def _reset_idle(self):
        self._overlay.hide()
        with self._lock:
            self._state = "IDLE"
        self._refresh_title()

    # ---------- historial ----------
    def _save_history_on(self) -> bool:
        return bool(self.cfg.get("app.save_history", True))

    def _push_history(self, text: str):
        self._history.appendleft(text)
        # deshace un filtro de búsqueda previo. Se llama desde el hilo de
        # _process (fondo): el write del título del NSMenuItem va por el main.
        self._on_main(lambda: setattr(self.recent_parent, "title", "Recent"))
        self._refresh_recent()
        if self._save_history_on():
            history.append(text, self.mode)

    def _refresh_recent(self):
        """Vuelca self._history al submenú Recent. Se llama desde el hilo de
        _process y de _warmup (fondo): mutar title/setHidden_ de un NSMenuItem
        con el menú abierto crashea (SIGTRAP), así que TODO va por _on_main.
        (Solo actualiza NSMenuItems ya creados; añadir/quitar no se hace aquí.)"""
        def apply():
            try:
                self._recent_empty._menuitem.setHidden_(len(self._history) > 0)
                for i, mi in enumerate(self._recent_items):
                    if i < len(self._history):
                        t = self._history[i].replace("\n", " ")
                        mi.title = (t[:57] + "…") if len(t) > 58 else t
                        mi._menuitem.setHidden_(False)
                    else:
                        mi._menuitem.setHidden_(True)
            except Exception:
                log.debug("No pude refrescar el submenú Recent", exc_info=True)
        self._on_main(apply)

    def _search_history(self, _sender):
        if not self._save_history_on():
            self._alert(
                "History is off",
                "Set app.save_history: true in config.yaml to keep dictations.",
            )
            return
        resp = rumps.Window(
            message="Find past dictations containing:",
            title="Search history",
            ok="Search",
            cancel="Cancel",
            dimensions=(300, 24),
        ).run()
        query = (resp.text or "").strip() if resp.clicked else ""
        if not query:
            return
        hits = history.search(query, HISTORY_SIZE)
        if not hits:
            self._alert("No matches", f'Nothing matches "{query}".')
            return
        # Los resultados se sirven en el propio submenú Recent (clic = copiar);
        # el siguiente dictado lo devuelve a "Recent" normal.
        self._history.clear()
        for t in reversed(hits):
            self._history.appendleft(t)
        self.recent_parent.title = f"Recent — “{query}”"
        self._refresh_recent()
        self._alert(
            f"{len(hits)} match(es)",
            "They're in the Recent submenu — click one to copy it.",
        )

    def _make_recent_cb(self, i: int):
        def cb(_sender):
            if i < len(self._history):
                output.copy_to_clipboard(self._history[i])
                self._hud(self._history[i][:80], title="✓ Copied to clipboard")
        return cb

    # ---------- settings ----------
    def _build_stt_prompt(self) -> str | None:
        terms = [str(t).strip() for t in (self.cfg.get("stt.dictionary", []) or [])]
        try:
            for t in dictionary.stt_terms():
                if t not in terms:
                    terms.append(t)
        except Exception:
            log.debug("No pude leer el diccionario personal", exc_info=True)
        return ", ".join(t for t in terms if t)[:600] or None

    def _add_to_dictionary(self, _sender):
        resp = rumps.Window(
            message=(
                "A word Whisper misspells (e.g. Ucademy), or a fix:\n"
                "wrong spelling -> right spelling"
            ),
            title="Add to dictionary",
            ok="Add",
            cancel="Cancel",
            dimensions=(300, 24),
        ).run()
        entry = (resp.text or "").strip() if resp.clicked else ""
        if not entry:
            return
        try:
            desc = dictionary.add(entry)
        except ValueError as e:
            self._alert("Not added", str(e))
            return
        self.stt_prompt = self._build_stt_prompt()  # sesga ya el próximo dictado
        self._hud(desc, title="✓ Added to dictionary")

    def _install_launch_agent(self) -> bool:
        try:
            os.makedirs(os.path.dirname(LAUNCH_AGENT), exist_ok=True)
            with open(LAUNCH_AGENT, "wb") as f:
                # `open -a` en vez del binario directo: no duplica instancia
                # si Voooxly ya está corriendo y sobrevive a que muevan el .app
                plistlib.dump(
                    {
                        "Label": "com.eduardocrovetto.voooxly",
                        "ProgramArguments": ["/usr/bin/open", "-a", "Voooxly"],
                        "RunAtLoad": True,
                    },
                    f,
                )
            return True
        except Exception:
            log.exception("No pude crear el LaunchAgent")
            return False

    def _apply_login_default(self):
        """Start at login viene activado de fábrica, UNA sola vez.

        Una app de hotkey solo sirve si está corriendo: si el usuario reinicia
        y Voooxly no arranca, el hotkey "no funciona". Si el usuario lo desactiva
        en Settings, el flag en prefs evita re-activárselo jamás.
        """
        if self._prefs.get("login_default_applied"):
            return
        if not os.path.exists(LAUNCH_AGENT) and self._install_launch_agent():
            self.login_item.state = 1
            log.info("Start at login activado por defecto (primera ejecución).")
        self._prefs["login_default_applied"] = True
        _save_prefs(self._prefs)

    def _toggle_login(self, sender):
        if sender.state:
            try:
                os.unlink(LAUNCH_AGENT)
            except FileNotFoundError:
                pass
            except Exception:
                log.exception("No pude quitar el LaunchAgent")
                return
            sender.state = 0
        else:
            if self._install_launch_agent():
                sender.state = 1

    def _toggle_sounds(self, sender):
        self._sounds = not self._sounds
        sender.state = 1 if self._sounds else 0
        self._prefs["sounds"] = self._sounds
        _save_prefs(self._prefs)
        if self._sounds:
            self._play_sound("Pop")

    def _make_key_cb(self, key: str):
        def cb(_sender):
            self._set_dictation_key(key)
        return cb

    def _make_style_cb(self, mode: str):
        def cb(_sender):
            self._set_dictation_style(mode)
        return cb

    def _set_dictation_key(self, key: str):
        ok, msg = keys.validate_custom(key)
        if not ok:
            self._alert("Can't use that key", msg)
            return
        # Choque con las otras teclas: la de dictado no puede ser también la
        # de cancelar ni la de latch, o una de las dos deja de funcionar.
        # keys._RESERVADAS ya filtra esto para el catálogo y para el YAML,
        # pero el hotkey lo vuelve a comprobar en reconfigure() — este chequeo
        # de aquí solo da un mensaje más específico (qué tecla es y de quién)
        # antes de intentar el reinicio en caliente.
        for otra, dueno in ((self._hotkey._cancel_key, "cancel"), (self._hotkey._latch_key, "latch")):
            if otra and (key == otra or key.startswith(otra + "_")):
                self._alert("Can't use that key", f"“{key}” is already the {dueno} key.")
                return
        aplicado = self._restart_hotkey(key, self._toggle_mode)
        if not aplicado:
            # reconfigure() rechazó la tecla (choca con cancel/latch pese al
            # chequeo de arriba, p.ej. un alias que _canon() colapsa igual).
            # No se toca prefs.json ni el checkmark: lo que está sonando de
            # verdad sigue siendo la tecla anterior.
            self._alert(
                "Can't use that key",
                f"“{key}” collides with the cancel or latch key, so the "
                "previous dictation key is still active.",
            )
            return
        self._prefs["dictation_key"] = key
        _save_prefs(self._prefs)
        etiqueta = keys.get(key).label if keys.get(key) else key
        if key == "ctrl_l":
            # No es un bug de hotkey.py: Ctrl+Shift+M (cycle mode) usa la
            # misma tecla física, así que al soltar la ventana de decisión
            # el chord dispara los dos a la vez. Elegir esta tecla es
            # legítimo (el usuario la pidió), pero hay que avisar — no
            # bloquear la elección.
            self._alert(
                "Heads up",
                "Left Control is now your dictation key. Ctrl+Shift+M "
                "(cycle dictation style) uses the same key, so that "
                "shortcut will fire together with dictation from now on.",
            )
        self._hud(etiqueta, title="✓ Dictation key changed")

    def _set_dictation_style(self, mode: str):
        if mode not in keys.MODES:
            return
        aplicado = self._restart_hotkey(self._dictation_key, mode)
        if not aplicado:
            self._alert(
                "Can't change style",
                "The current dictation key no longer works with the hotkey "
                "engine; pick a different dictation key first.",
            )
            return
        self._prefs["dictation_mode"] = mode
        _save_prefs(self._prefs)
        self._hud(keys.MODES[mode], title="✓ Dictation style changed")

    def _restart_hotkey(self, new_key: str, new_mode: str) -> bool:
        """Aplica tecla/modo nuevos al listener que ya está corriendo.

        El nombre dice "restart" por historia: hoy NO se para ni se rearranca
        nada. Ese rearranque mataba la app (ver el comentario de apply()) y
        además nunca hizo falta, porque reconfigure() solo cambia atributos que
        los callbacks releen en cada evento.

        POR EL HILO PRINCIPAL, siempre: las marcas del menú son NSMenuItem, y
        escribirlas desde un hilo de fondo es el SIGTRAP que documenta el
        header de hotkey.py.

        Devuelve si el cambio se aplicó de verdad. reconfigure() puede
        rechazar `new_key` (choca con cancel/latch) y entonces deja su config
        interna intacta — self._dictation_key/self._toggle_mode y las marcas
        del menú tienen que reflejar ESE resultado, nunca lo que se pidió, o
        el checkmark mentiría sobre qué tecla está activa de verdad.

        INVARIANTE (antes implícito, ahora explícito): esta función lee
        resultado["ok"] justo después de llamar a self._on_main(apply), y eso
        solo es correcto si _on_main ejecuta apply() de forma SÍNCRONA — lo
        que _on_main.__doc__ solo garantiza en el hilo principal. Fuera de
        él, AppHelper.callAfter es asíncrono: se leería resultado["ok"] en su
        valor inicial (False) aunque la tecla sí hubiera cambiado, dejando
        prefs.json sin guardar y el checkmark del menú desincronizado de lo
        que el hotkey tiene activo de verdad. Hoy solo llegan aquí callbacks
        de menú de rumps, que ya corren en el hilo principal — el assert no
        cambia ese comportamiento, solo lo deja explícito para que un futuro
        llamador desde un hilo de fondo falle ruidosamente en vez de guardar
        mal en silencio.
        """
        assert threading.current_thread() is threading.main_thread(), (
            "_restart_hotkey debe llamarse desde el hilo principal: fuera de "
            "él, _on_main() es async y el resultado se leería antes de que "
            "apply() corra de verdad"
        )
        resultado = {"ok": False}

        def apply():
            # NO se para ni se rearranca el listener. Hacerlo mataba la app:
            # pynput arranca el suyo con `with keycode_context()`
            # (_darwin.py:272), que llama a TISGetInputSourceProperty DESDE EL
            # HILO DEL LISTENER. macOS exige el hilo principal para las APIs de
            # fuentes de entrada, pero solo lo comprueba cuando toca
            # reconstruir la lista — con la caché caliente pasa desapercibido.
            # Pulsar F5 (Dictado del sistema en un Mac) cambia la fuente de
            # entrada e invalida la caché: el rearranque siguiente la
            # reconstruía desde el hilo equivocado y HIToolbox mataba el
            # proceso con SIGTRAP en dispatch_assert_queue.
            #
            # Y nunca hizo falta: reconfigure() solo toca atributos normales
            # (_toggle_key, toggle_mode, _guard) y _on_press/_on_release los
            # leen en cada evento. El mismo listener obedece la tecla nueva.
            try:
                resultado["ok"] = self._hotkey.reconfigure(
                    toggle_key=new_key,
                    toggle_mode=new_mode,
                    guard=keys.needs_guard(new_key),
                )
            except Exception:
                log.exception("No pude reconfigurar el hotkey con la tecla nueva")
            if resultado["ok"]:
                self._dictation_key = new_key
                self._toggle_mode = new_mode
            for k, mi in self.key_items.items():
                mi.state = 1 if k == self._dictation_key else 0
            for m, mi in self.style_items.items():
                mi.state = 1 if m == self._toggle_mode else 0

        self._on_main(apply)
        return resultado["ok"]

    def _play_sound(self, name: str):
        if not self._sounds:
            return
        try:
            from AppKit import NSSound

            snd = self._snd_cache.get(name)
            if snd is None:
                snd = NSSound.soundNamed_(name)
                if snd is None:
                    return
                snd.setVolume_(0.35)   # sutil, estilo Wispr
                self._snd_cache[name] = snd
            snd.stop()   # por si sigue sonando de la vez anterior
            snd.play()
        except Exception:
            pass

    # ---------- acciones de menú ----------
    def paste_last(self):
        if self._last_result:
            output.copy_to_clipboard(self._last_result)
            output.paste_frontmost()

    def _update_ai_item(self, force: bool = True) -> str:
        """Marca el proveedor activo en el submenú. Devuelve su clave.

        Los writes de AppKit (mi.state, self.ai.title) van por _on_main: esto se
        llama desde el hilo _warmup (detección inicial + keepalive cada N min),
        no solo desde callbacks de menú. detect_backend (red) se queda en el hilo
        llamante para devolver el valor de forma síncrona."""
        from . import ai_settings

        sel = ai_settings.load(self._prefs)
        if sel is None:
            detected = refine.detect_backend(self.cfg, force=force)
            title = ai_engine_title(sel, detected)
            ret = detected
        else:
            title = ai_engine_title(sel, "")
            ret = sel.provider.key

        def apply():
            for prov_key, mi in self._ai_items.items():
                mi.state = 1 if (sel and sel.provider.key == prov_key) else 0
            self.ai.title = title
        self._on_main(apply)
        return ret

    def _apply_ai_selection(self, sel) -> None:
        """Delegado fino: la lógica vive en apply_ai_selection (nivel de
        módulo) para poder testearla sin instanciar VoooxlyApp."""
        apply_ai_selection(self.cfg, sel)

    def _make_provider_cb(self, prov_key: str):
        def cb(_sender):
            self._connect_provider(prov_key)
        return cb

    def _connect_ai_from_onboarding(self):
        """Selector de proveedor para el paso "Connect AI" del onboarding, que
        delega en _connect_provider (flujo probado: pide key, valida, guarda en
        llavero + prefs). Lo conectado persiste tras el relanzamiento de la app.

        Nadie tiene IA en el primer arranque, así que aquí no hay "test": es
        conectar. Es opcional; el onboarding deja claro que el dictado va sin ella.
        """
        from AppKit import NSAlert, NSPopUpButton
        from Foundation import NSMakeRect

        from . import providers

        keys = list(providers.PROVIDERS.keys())
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Connect an AI engine")
        alert.setInformativeText_(
            "Pick a provider — Voooxly will ask for its API key next. It's "
            "optional; dictation works fine without it.")
        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(0, 0, 260, 26), False)
        for k in keys:
            popup.addItemWithTitle_(providers.PROVIDERS[k].label)
        alert.setAccessoryView_(popup)
        alert.addButtonWithTitle_("Continue")
        alert.addButtonWithTitle_("Cancel")
        if alert.runModal() != 1000:  # NSAlertFirstButtonReturn = Continue
            return
        self._connect_provider(keys[popup.indexOfSelectedItem()])

    def _connect_provider(self, prov_key: str):
        """Pide lo que falte, valida contra el proveedor y guarda si funciona."""
        from . import ai_settings, keychain, providers

        prov = providers.get(prov_key)
        if prov is None:
            return
        base_url, model = prov.base_url, prov.default_model

        if prov.kind == "ollama":
            # El modelo no se presupone: se le pregunta a SU Ollama (Task 5).
            # El host tampoco: llm.ollama.host puede venir de la config del
            # usuario o de VOOOXLY_LLM_OLLAMA_HOST (Ollama remoto), y hay que
            # sondear ESE host — y guardarlo como base_url de la selección,
            # para que lo probado sea exactamente lo que queda persistido.
            base_url = (
                self.cfg.get("llm.ollama.host", "")
                or base_url
                or "http://localhost:11434"
            )
            modelos = refine.list_ollama_models(base_url)
            if not modelos:
                self._alert(
                    "Ollama has no models",
                    "Install Ollama and pull a model (for example: "
                    "ollama pull llama3.2), then click here again.",
                )
                return
            listado = "\n".join(f"• {m}" for m in modelos)
            resp = rumps.Window(
                message=f"Models on your Ollama:\n{listado}\n\nType the one to use:",
                title="Choose your Ollama model",
                default_text=modelos[0],
                ok="Next", cancel="Cancel", dimensions=(320, 24),
            ).run()
            if not resp.clicked or not resp.text.strip():
                return
            model = resp.text.strip()

        api_key = None
        if prov.needs_key:
            api_key = keychain.get_key(prov.key)
            resp = rumps.Window(
                message=f"API key for {prov.name}:",
                title="Connect AI engine",
                ok="Connect", cancel="Cancel",
                dimensions=(320, 24), secure=True,
            ).run()
            if not resp.clicked:
                return
            if resp.text.strip():
                api_key = resp.text.strip()
            if not api_key:
                self._alert("No API key", f"{prov.name} needs a key to work.")
                return

        sel = ai_settings.Selection(prov, base_url, model)
        ok, msg = refine.validate(sel, api_key)
        if not ok:
            self._alert(f"Couldn't connect to {prov.name}", msg)
            return

        key_guardada = True
        if prov.needs_key and api_key:
            # set_key puede devolver False (llavero que rechaza la escritura):
            # la sesión sigue funcionando porque la key ya está exportada y
            # validada, pero al reiniciar desaparecería en silencio. Seguimos
            # adelante (castigar dos veces al usuario no arregla el llavero)
            # y cambiamos el alert final por un aviso honesto.
            key_guardada = keychain.set_key(prov.key, api_key)
        self._prefs = ai_settings.save(self._prefs, prov.key, base_url, model)
        _save_prefs(self._prefs)
        # Sin esto, hasta el siguiente reinicio la app dictaría con la config
        # vieja: prefs.json solo se lee al arrancar. "Connected ✓" y luego nada.
        self._apply_ai_selection(ai_settings.load(self._prefs))
        refine.detect_backend(self.cfg, force=True)
        self._update_ai_item(force=False)
        if key_guardada:
            self._alert("AI engine connected", msg)
        else:
            self._alert(
                "Connected — but the key wasn't saved",
                "Your key works for this session, but macOS Keychain refused "
                "to store it. You'll be asked for it again after restarting "
                "Voooxly.",
            )

    def _test_ai(self, _sender):
        from . import ai_settings, keychain

        sel = ai_settings.load(self._prefs)
        if sel is None:
            self._alert("No AI engine selected", "Pick one from the AI engine menu first.")
            return
        api_key = keychain.get_key(sel.provider.key) if sel.provider.needs_key else None
        ok, msg = refine.validate(sel, api_key)
        self._alert("Connection OK" if ok else "Connection failed", msg)

    def _reset_to_auto(self, _sender):
        """Devuelve el control a la cascada de auto-detección."""
        from . import ai_settings

        for clave in (ai_settings.CLAVE_PROVEEDOR, ai_settings.CLAVE_BASE_URL,
                      ai_settings.CLAVE_MODELO):
            self._prefs.pop(clave, None)
        _save_prefs(self._prefs)
        self.cfg._set_path("llm.backend", "auto")
        b = refine.detect_backend(self.cfg, force=True)
        self._update_ai_item(force=False)
        self._alert("Back to automatic", f"Detected: {b}.")

    def _open_update(self, _sender):
        if not self._update_url or self._update_downloading:
            return
        self._update_downloading = True
        threading.Thread(target=self._download_update, daemon=True).start()

    def _download_update(self):
        # Descarga el DMG a ~/Downloads y lo abre montado: al usuario solo le
        # queda arrastrar a Applications. Si la descarga falla, se abre la URL
        # en el navegador (el comportamiento antiguo) para no dejarle tirado.
        version = self._update_version or "latest"
        self._hud("The menu bar icon shows progress.", title=f"⏬ Downloading Voooxly {version}")
        try:
            path = updates.download(
                self._update_url, version,
                progress_cb=lambda p: setattr(self, "title", f"⏬ {p}%"),
            )
        finally:
            self._update_downloading = False
            self._refresh_title()
        if path:
            subprocess.run(["open", str(path)], check=False)
            self._alert(
                "Update downloaded",
                "Drag Voooxly into Applications to replace this version, then relaunch.",
            )
        else:
            subprocess.run(["open", self._update_url], check=False)

    def _show_about(self, _sender):
        """Diálogo About: icono, versión y un botón para comprobar updates."""
        from AppKit import (
            NSAlert,
            NSAlertFirstButtonReturn,
            NSAlertStyleInformational,
            NSApp,
        )

        alert = NSAlert.alloc().init()
        alert.setMessageText_("Voooxly")
        alert.setInformativeText_(
            f"Version {updates.current_version()}\n\nLocal dictation on your Mac."
        )
        alert.setIcon_(NSApp.applicationIconImage())
        alert.setAlertStyle_(NSAlertStyleInformational)
        alert.addButtonWithTitle_("Check for updates…")
        alert.addButtonWithTitle_("OK")
        if alert.runModal() == NSAlertFirstButtonReturn:
            self._check_now(None)

    def _check_now(self, _sender):
        """Check manual (vía el botón de About). Offload a hilo; alert con el resultado."""
        def _work():
            status, info = updates.check_status()
            def _on_done():
                if status == updates.UPDATE_AVAILABLE and info:
                    self._update_url = info["url"]
                    self._update_version = info["version"]
                    ver = info["version"]

                    def _show():
                        self.update_item.title = f"Update to {ver} →"
                        self.update_item._menuitem.setHidden_(False)

                    self._on_main(_show)
                title, message = check_now_message(
                    status, info, updates.current_version()
                )
                self._alert(title, message)

            self._on_main(_on_done)

        threading.Thread(target=_work, daemon=True).start()

    def _schedule_update_check(self):
        """Re-chequeo cada updates.CHECK_INTERVAL. Se reagenda a sí mismo; cancelable."""
        self._update_timer = threading.Timer(
            updates.CHECK_INTERVAL, self._periodic_update_check
        )
        self._update_timer.daemon = True
        self._update_timer.start()

    def _periodic_update_check(self):
        # Silencioso salvo la primera vez que aparece una versión nueva: HUD
        # efímero (una vez por versión) + el ítem de menú. Fallos de red: log.
        try:
            info = updates.check()
            if info:
                self._update_url = info["url"]
                self._update_version = info["version"]
                ver = info["version"]

                def _show():
                    self.update_item.title = f"Update to {ver} →"
                    self.update_item._menuitem.setHidden_(False)

                self._on_main(_show)
                if updates.should_notify(info, self._notified_update_version):
                    self._notified_update_version = ver
                    self._on_main(
                        lambda: self._hud(
                            "See the menu to install.",
                            title=f"Voooxly {ver} is available",
                        )
                    )
        except Exception:
            log.debug("re-chequeo periódico falló (ignorado)", exc_info=True)
        finally:
            self._schedule_update_check()

    def _show_stats(self, _sender):
        self._alert("Your dictation stats", stats.summary())

    def _quit(self, _sender):
        try:
            self._partial_running.clear()
            if self._recorder:
                self._recorder.stop()
            if self._hotkey:
                self._hotkey.stop()
            if self._update_timer:
                self._update_timer.cancel()
            stt.stop_server()
        finally:
            rumps.quit_application()

    # ---------- lifecycle ----------
    def run(self):
        # Crea NSApplication en el main thread ANTES de iniciar pynput: el Listener
        # de pynput llama a TIS/TSM desde su hilo y si compite con la inicialización
        # de NSApplication (que también toca TSM) macOS aborta con SIGABRT.
        from AppKit import NSApplication

        _ = NSApplication.sharedApplication()
        # Construye ya el Controller de pynput: su __init__ consulta TIS/TSM y
        # hacerlo luego, desde el hilo de _process, compite con el listener del
        # hotkey y HIToolbox mata el proceso (SIGTRAP, incapturable). Aquí no hay
        # más hilos todavía y estamos en el main thread, que es donde TSM quiere.
        output.warmup()
        # La key vive en el llavero; los backends la leen de os.environ. Sin este
        # puente la conexión se pierde en cada reinicio.
        try:
            from . import ai_settings, keychain

            sel = ai_settings.load(self._prefs)
            if sel and sel.provider.needs_key:
                refine.export_key(sel, keychain.get_key(sel.provider.key))
            # Mismo helper que usa _connect_provider: escribir llm.openai.base_url
            # incondicionalmente aquí era el mismo bug de rutas por kind que la
            # revisión cazó en _probe (Task 4), repetido en el arranque.
            self._apply_ai_selection(sel)
        except Exception:
            log.warning("No pude restaurar el proveedor guardado", exc_info=True)
        # Construye el overlay en el main thread ANTES de cualquier dictado:
        # NSPanel solo puede instanciarse aquí (AppKit lanza si se hace desde el hilo
        # del hotkey al pulsar la tecla de dictado).
        if self._show_overlay:
            try:
                self._overlay.build()
            except Exception as e:
                log.warning("No se pudo construir el overlay: %s", e)
        # Primer arranque (o permiso revocado): el asistente explica qué falta y
        # guía cada paso. Va aquí, en el main thread, porque NSWindow no puede
        # instanciarse fuera de él. No bloquea: la ventana convive con la app.
        # needs_setup() sondea permisos (micro, Accesibilidad): se llama UNA vez
        # y se reutiliza. Por defecto True para que un fallo del sondeo deje la
        # limpieza en paz en vez de soltar un alert sobre un arranque ya roto.
        needs_setup = True
        try:
            needs_setup = setup_checks.needs_setup()
            if needs_setup:
                from .onboarding import show_onboarding

                show_onboarding(on_finish=self._on_onboarding_done,
                                on_connect_ai=self._connect_ai_from_onboarding)
        except Exception as e:
            log.warning("No pude mostrar el onboarding: %s", e)
        # Setup ya completo: si el DMG del instalador sigue montado, ofrecemos
        # expulsarlo y mandarlo a la papelera. Va aquí, en el main thread, que es
        # lo que exige el NSAlert. Pregunta una sola vez (flag en prefs).
        if not needs_setup:
            from AppKit import NSBundle

            from .installer_cleanup import maybe_clean_up

            maybe_clean_up(self._prefs, _save_prefs,
                           str(NSBundle.mainBundle().bundlePath()))
        # arranca whisper-server en background para que el primer dictado no pague el coste
        threading.Thread(target=self._warmup, daemon=True).start()
        self._hotkey.start()
        super().run()

    def _on_onboarding_done(self):
        """Relanza la app como proceso NUEVO al cerrar el onboarding.

        En run() el listener de pynput arranca ANTES de que se conceda
        Accesibilidad: sin ese permiso el CGEventTap no se crea y no llegan
        eventos globales. Conceder el permiso a mitad — o incluso rearrancar el
        listener in-process (stop+start) — NO basta: macOS no re-evalúa el
        permiso de Accesibilidad para el event tap dentro del mismo proceso.
        Lo confirma el usuario: tras reabrir la app (proceso nuevo) dicta; el
        rearranque in-process, no. La forma fiable es relanzar la app: con el
        permiso ya persistido en TCC, el proceso nuevo crea un event tap válido
        y el hotkey funciona sin más. Solo pasa en el primer arranque.
        """
        import subprocess
        from AppKit import NSBundle

        relanzado = False
        try:
            bundle = str(NSBundle.mainBundle().bundlePath())
            # Solo relanzamos si vamos como .app (instalado). En dev (python -m)
            # bundlePath() no es un .app y `open -n` haría algo raro.
            if bundle.endswith(".app"):
                subprocess.Popen(["open", "-n", bundle])
                relanzado = True
                # un instante para que launchd registre el nuevo proceso y salir
                threading.Timer(0.5, self._quit_for_relaunch).start()
        except Exception:
            log.warning("No pude relanzar Voooxly tras el onboarding", exc_info=True)

        if not relanzado:
            # Fallback (dev sin bundle): rearrancar el listener in-process. No
            # es tan fiable como relanzar, pero al menos lo intenta.
            try:
                self._hotkey.stop()
                self._hotkey.start()
                log.info("Hotkey rearrancado in-process (modo dev).")
            except Exception:
                log.warning("No pude rearrancar el hotkey", exc_info=True)

    def _quit_for_relaunch(self):
        # terminate() toca AppKit: va por el hilo principal.
        self._on_main(lambda: rumps.quit_application())

    def _warmup(self):
        # 0) modelo de voz: si no está, se descarga solo con progreso en el icono
        try:
            if not stt.find_model():
                self._alert(
                    "Downloading speech model",
                    "~550MB, one time only — the menu bar icon shows progress.",
                )

                def _dl_progress(pct: int):
                    # corre en el hilo de _warmup: el título va por el main.
                    self._on_main(lambda p=pct: setattr(self, "title", f"⏬ {p}%"))

                ok_model = stt.ensure_model(progress_cb=_dl_progress)
                self._refresh_title()
                if ok_model:
                    self._hud("Speech model installed.", title="✓ Ready")
                else:
                    self._alert(
                        "Model download failed",
                        "Check your connection and relaunch Voooxly.",
                    )
        except Exception as e:
            log.warning("Auto-descarga de modelo falló: %s", e)
            self._refresh_title()
        # 1) whisper-server
        try:
            port = int(self.cfg.get("stt.server_port", 8080))
            threads = int(self.cfg.get("stt.threads", 4))
            ok = stt.start_server(threads=threads, port=port)
            if not ok:
                log.warning(
                    "whisper-server no arrancó. Verifica 'brew install whisper-cpp' "
                    "y el modelo en ~/.voooxly/models/ (ver README)."
                )
        except Exception as e:
            log.warning("Warmup STT falló (se intentará al primer uso): %s", e)
        # 2) detección del motor LLM disponible
        try:
            self._update_ai_item(force=True)
        except Exception:
            pass
        # 3) aviso de versión nueva (silencioso si no hay red o el appcast falla)
        try:
            info = updates.check()
            if info:
                self._update_url = info["url"]
                self._update_version = info["version"]
                # Si ya hay novedad al arranque, la contamos como "avisada" para
                # que el re-chequeo periódico no suelte el HUD 24 h después por la
                # misma versión: el HUD es para versiones que aparecen NUEVAS
                # mientras la app está abierta.
                self._notified_update_version = info["version"]
                ver = info["version"]

                def _show_update():
                    self.update_item.title = f"Update to {ver} →"
                    self.update_item._menuitem.setHidden_(False)

                self._on_main(_show_update)
        except Exception:
            pass
        finally:
            # El re-chequeo periódico debe armarse tanto si el check de
            # arranque tuvo éxito como si falló (sin red / appcast caído):
            # si va al `except` y `_schedule_update_check()` queda dentro del
            # `try`, el timer 24 h nunca se arrancaría y las versiones que
            # aparecen con la app abierta pasarían inadvertidas hasta el
            # siguiente reinicio.
            self._schedule_update_check()
        # 4) sembrar Recent con el historial persistente de sesiones anteriores
        try:
            if self._save_history_on() and not self._history:
                for t in reversed(history.load(HISTORY_SIZE)):
                    self._history.appendleft(t)
                if self._history:
                    self._refresh_recent()
        except Exception:
            pass
        # Keepalive: en Macs con poca RAM macOS pagina el modelo (~1.6GB) tras
        # inactividad y el siguiente dictado paga 10-19s de vuelta a memoria.
        # Un ping de 0.4s de silencio cada N min lo mantiene caliente (~0.3s de
        # coste). stt.keepalive_min: 0 lo desactiva.
        try:
            mins = float(self.cfg.get("stt.keepalive_min", 4))
        except (TypeError, ValueError):
            mins = 4.0
        if mins <= 0:
            return
        import numpy as np

        ping = np.zeros(int(0.4 * audio.SR), dtype=np.int16)
        while True:
            time.sleep(mins * 60)
            with self._lock:
                busy = self._state != "IDLE"
            if busy:
                continue
            try:
                stt.transcribe(ping, self.stt_model, "es")
                # re-detección barata: si el usuario arrancó Ollama después de
                # abrir Voooxly, el menú se entera solo
                self._update_ai_item(force=True)
            except Exception:
                pass