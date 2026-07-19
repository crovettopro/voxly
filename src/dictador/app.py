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

from . import audio, dictionary, history, media, modes, output, refine, setup_checks, stats, stt, updates
from .config import get_config, resolve_language
from .hotkey import HotkeyManager
from .overlay import Overlay

log = logging.getLogger("dictador")

# Preferencias que se tocan desde el menú (el config.yaml va DENTRO del .app y
# es de solo lectura en la práctica): un json pequeño en ~/.dictador.
PREFS_PATH = os.path.expanduser("~/.dictador/prefs.json")
# "Start at login": un LaunchAgent clásico — sin APIs de ServiceManagement,
# funciona igual lanzado desde el repo o desde /Applications.
LAUNCH_AGENT = os.path.expanduser(
    "~/Library/LaunchAgents/com.eduardocrovetto.dictador.plist"
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


class DictadorApp(rumps.App):
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

        icon_path = self._menubar_icon_path()
        self._has_icon = icon_path is not None
        super().__init__(
            name="Voxly",
            icon=icon_path,          # glyph template (se adapta a claro/oscuro)
            title=None if self._has_icon else "🎙",
            template=True,
            quit_button=None,        # rumps añade un "Quit" propio si no se anula
        )                            # (usamos el nuestro, que apaga server/hotkey)
        self._build_menu()
        self._apply_login_default()
        self._toggle_mode = cfg.get("hotkeys.toggle_mode", "toggle")
        self._hotkey = HotkeyManager(
            toggle_mode=self._toggle_mode,
            toggle_keys=cfg.get("hotkeys.toggle", ["cmd_r"]),
            cycle_keys=cfg.get("hotkeys.cycle_mode", ["ctrl", "shift", "m"]),
            paste_keys=cfg.get("hotkeys.paste_last", ["ctrl", "shift", "v"]),
            on_toggle=self.toggle_record,
            on_start=self.start_record,
            on_stop=self.stop_record,
            on_cycle=self.cycle_mode,
            on_paste=self.paste_last,
            cancel_keys=cfg.get("hotkeys.cancel", ["esc"]),
            on_cancel=self.cancel_record,
        )

    @staticmethod
    def _menubar_icon_path() -> str | None:
        import os
        import sys

        cands = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            cands.append(os.path.join(meipass, "assets", "menubar.png"))
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cands.append(os.path.join(repo, "assets", "menubar.png"))
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
        self.ai = rumps.MenuItem("AI: detecting…", callback=self._redetect_ai)
        self.health = rumps.MenuItem("Backend status…", callback=self.show_health)
        self.stats_item = rumps.MenuItem("Usage stats…", callback=self._show_stats)
        self.quit = rumps.MenuItem("Quit Voxly", callback=self._quit)
        # Oculto hasta que el comprobador encuentre una versión nueva (ver _warmup).
        self.update_item = rumps.MenuItem("Update available", callback=self._open_update)
        self._update_url = ""
        self._update_version = ""
        self._update_downloading = False
        self._paused_players: list[str] = []

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

        self.search_item = rumps.MenuItem("Search history…", callback=self._search_history)

        self.menu = [
            *items,
            rumps.separator,
            self.recent_parent,
            self.search_item,
            rumps.separator,
            self.status,
            self.ai,
            self.health,
            self.stats_item,
            settings,
            rumps.separator,
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
        for k, mi in self.mode_items.items():
            mi.state = 1 if k == key else 0
        self._refresh_title()
        log.info("Modo: %s", modes.MODES[key]["label"])

    def cycle_mode(self):
        keys = list(modes.MODES.keys())
        try:
            i = keys.index(self.mode)
        except ValueError:
            i = -1
        self.set_mode(keys[(i + 1) % len(keys)])

    def _refresh_title(self):
        label = modes.MODES.get(self.mode, {}).get("label", "Voxly")
        state = self._state
        # barra de menú minimalista: glyph solo en reposo, emoji de estado activo
        self.title = {"RECORDING": "🔴", "PROCESSING": "⏳"}.get(
            state, None if self._has_icon else "🎙"
        )
        state_en = {"IDLE": "ready", "RECORDING": "recording", "PROCESSING": "processing"}
        self.status.title = f"Mode: {label} · {state_en.get(state, state)}"

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
            max_duration=self.cfg.get("audio.max_duration", 60.0),
            min_duration=self.cfg.get("audio.min_duration", 0.4),
        )
        self._recorder = audio.Recorder(acfg)
        if self._show_overlay:
            self._overlay.show("Listening — speak now.")
        # hilo de partials: re-transcribe la ventana reciente
        self._partial_running.set()
        self._partial_thread = threading.Thread(target=self._partial_loop, daemon=True)
        self._partial_thread.start()
        self._recorder.start(on_stop=self._on_stop)
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
        self._overlay.update("Transcribing…")
        threading.Thread(
            target=self._process,
            args=(audio_buf, duration, had_speech, speech_ratio),
            daemon=True,
        ).start()

    def _flash(self, msg: str, secs: float = 1.6):
        """Mensaje breve en el HUD (el finally de _process lo cierra después)."""
        try:
            self._overlay.update(msg)
            time.sleep(secs)
        except Exception:
            pass

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
            # 0) guardas: nunca mandar silencio a Whisper (alucina "Gracias"/"Thank you")
            level = audio.rms_of(audio_buf)
            if level < self._min_rms():
                log.warning(
                    "Micrófono sin señal (RMS=%.0f). ¿Permiso de Micrófono concedido?", level
                )
                self._flash("🎤 No audio captured — check Microphone permission", 2.5)
                rumps.notification(
                    "Voxly",
                    "Microphone is silent",
                    "System Settings → Privacy & Security → Microphone → enable Voxly.",
                )
                return
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
            self._overlay.update(f"✨ {transcript}")
            # 2) refino por modo (si falla, cae a la transcripción cruda: nunca bloquea)
            # Fast-lane: dictados cortos en modos marcados se pegan tal cual —
            # Whisper ya puntúa bien frases breves y ahorramos 2-6s de LLM.
            fast_words = int(self.cfg.get("llm.fast_lane_words", 9))
            n_words = len(transcript.split())
            if (
                fast_words > 0
                and modes.MODES.get(self.mode, {}).get("fast_lane")
                and n_words <= fast_words
            ):
                log.info("Fast-lane (%d palabras): sin refino LLM.", n_words)
                final = transcript
            else:
                try:
                    final = refine.Refiner(self.cfg).refine(transcript, self.mode, self.language)
                except Exception:
                    log.exception("Refinado falló; uso transcripción cruda")
                    final = transcript
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
            status = output.deliver(final, auto_paste=auto_paste, copy=copy)
            if auto_paste and status == "copied":
                # El pegado falló pero el texto SÍ está en el portapapeles:
                # sin este aviso el usuario ve que "no pasa nada" y lo pierde.
                rumps.notification(
                    "Voxly",
                    "Couldn't paste into the active app",
                    "Your text is on the clipboard — press ⌘V to paste it.",
                )
                self._flash("Copied — press ⌘V to paste", 2.2)
            else:
                # mostrar resultado breve y cerrar
                self._overlay.update(final)
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
        self.recent_parent.title = "Recent"  # deshace un filtro de búsqueda previo
        self._refresh_recent()
        if self._save_history_on():
            history.append(text, self.mode)

    def _refresh_recent(self):
        """Vuelca self._history al submenú Recent (solo title/hidden: seguro
        desde hilos de fondo; añadir/quitar NSMenuItems no lo sería)."""
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

    def _search_history(self, _sender):
        if not self._save_history_on():
            rumps.notification(
                "Voxly", "History is off",
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
            rumps.notification("Voxly", "No matches", f'Nothing matches "{query}".')
            return
        # Los resultados se sirven en el propio submenú Recent (clic = copiar);
        # el siguiente dictado lo devuelve a "Recent" normal.
        self._history.clear()
        for t in reversed(hits):
            self._history.appendleft(t)
        self.recent_parent.title = f"Recent — “{query}”"
        self._refresh_recent()
        rumps.notification(
            "Voxly", f"{len(hits)} match(es)",
            "They're in the Recent submenu — click one to copy it.",
        )

    def _make_recent_cb(self, i: int):
        def cb(_sender):
            if i < len(self._history):
                output.copy_to_clipboard(self._history[i])
                rumps.notification("Voxly", "Copied to clipboard", self._history[i][:80])
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
            rumps.notification("Voxly", "Not added", str(e))
            return
        self.stt_prompt = self._build_stt_prompt()  # sesga ya el próximo dictado
        rumps.notification("Voxly", "Added to dictionary", desc)

    def _install_launch_agent(self) -> bool:
        try:
            os.makedirs(os.path.dirname(LAUNCH_AGENT), exist_ok=True)
            with open(LAUNCH_AGENT, "wb") as f:
                # `open -a` en vez del binario directo: no duplica instancia
                # si Voxly ya está corriendo y sobrevive a que muevan el .app
                plistlib.dump(
                    {
                        "Label": "com.eduardocrovetto.dictador",
                        "ProgramArguments": ["/usr/bin/open", "-a", "Voxly"],
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
        y Voxly no arranca, el hotkey "no funciona". Si el usuario lo desactiva
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
        b = refine.detect_backend(self.cfg, force=force)
        labels = {
            "ollama": "AI: Ollama ✓",
            "claude": "AI: Claude API ✓",
            "openai": "AI: OpenAI-compatible ✓",
            "none": "AI: none — pasting raw text",
        }
        self.ai.title = labels.get(b, f"AI: {b}")
        return b

    def _redetect_ai(self, _sender):
        b = self._update_ai_item(force=True)
        if b == "none":
            rumps.notification(
                "Voxly",
                "No AI engine found",
                "Start Ollama, or add ANTHROPIC_API_KEY / OPENAI_API_KEY to "
                "~/.dictador/.env — then click here again.",
            )
        else:
            rumps.notification("Voxly", "AI engine", self.ai.title)

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
        rumps.notification(
            "Voxly", f"Downloading Voxly {version}…",
            "The menu bar icon shows progress.",
        )
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
            rumps.notification(
                "Voxly", "Update downloaded",
                "Drag Voxly into Applications to replace this version, then relaunch.",
            )
        else:
            subprocess.run(["open", self._update_url], check=False)

    def _show_stats(self, _sender):
        rumps.notification("Voxly", "Your dictation stats", stats.summary())

    def show_health(self, _sender):
        h = refine.health()
        msg = " · ".join(f"{k}: {'✓' if v else '✗'}" for k, v in h.items())
        rumps.notification("Voxly", "Backends", msg)
        self.status.title = msg

    def _quit(self, _sender):
        try:
            self._partial_running.clear()
            if self._recorder:
                self._recorder.stop()
            if self._hotkey:
                self._hotkey.stop()
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
        try:
            if setup_checks.needs_setup():
                from .onboarding import show_onboarding

                show_onboarding()
        except Exception as e:
            log.warning("No pude mostrar el onboarding: %s", e)
        # arranca whisper-server en background para que el primer dictado no pague el coste
        threading.Thread(target=self._warmup, daemon=True).start()
        self._hotkey.start()
        super().run()

    def _warmup(self):
        # 0) modelo de voz: si no está, se descarga solo con progreso en el icono
        try:
            if not stt.find_model():
                rumps.notification(
                    "Voxly",
                    "Downloading speech model",
                    "~550MB, one time only — the menu bar icon shows progress.",
                )

                def _dl_progress(pct: int):
                    self.title = f"⏬ {pct}%"

                ok_model = stt.ensure_model(progress_cb=_dl_progress)
                self._refresh_title()
                if ok_model:
                    rumps.notification("Voxly", "Ready", "Speech model installed.")
                else:
                    rumps.notification(
                        "Voxly", "Model download failed",
                        "Check your connection and relaunch Voxly.",
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
                    "y el modelo en ~/.dictador/models/ (ver README)."
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
                self.update_item.title = f"Update to {info['version']} →"
                self.update_item._menuitem.setHidden_(False)
        except Exception:
            pass
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
                # abrir Voxly, el menú se entera solo
                self._update_ai_item(force=True)
            except Exception:
                pass