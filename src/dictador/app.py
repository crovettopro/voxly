"""App de barra de menús (rumps) que orquesta todo el sistema de dictado.

Máquina de estados simple:
  IDLE -> (toggle) -> RECORDING -> (toggle | silencio) -> PROCESSING -> IDLE

Durante RECORDING se muestra el overlay con transcripción parcial.
Al finalizar: STT final -> refino por modo -> entregar (clipboard + paste).
"""
from __future__ import annotations

import logging
import threading
import time

import rumps

from . import audio, modes, output, refine, stt
from .config import get_config
from .hotkey import HotkeyManager
from .overlay import Overlay

log = logging.getLogger("dictador")


class DictadorApp(rumps.App):
    def __init__(self):
        cfg = get_config()
        self.cfg = cfg
        self.mode = cfg.get("app.default_mode", "ordenar")
        self.language = cfg.get("app.language", None)
        self.stt_model = cfg.get("stt.model")
        self.stt_lang = cfg.get("stt.language", None)
        self._state = "IDLE"
        self._lock = threading.Lock()
        self._recorder: audio.Recorder | None = None
        self._overlay = Overlay(cfg.get("app.overlay_position", "bottom-right"))
        self._last_result = ""
        self._show_overlay = bool(cfg.get("app.show_overlay", True))
        self._partial_thread: threading.Thread | None = None
        self._partial_running = threading.Event()

        super().__init__(
            name="Dictador",
            icon=None,
            title="🎙",  # se actualiza con el modo
            template=True,
        )
        self._build_menu()
        self._hotkey = HotkeyManager(
            toggle_keys=cfg.get("hotkeys.toggle", ["f5"]),
            cycle_keys=cfg.get("hotkeys.cycle_mode", ["ctrl", "shift", "m"]),
            paste_keys=cfg.get("hotkeys.paste_last", ["ctrl", "shift", "v"]),
            on_toggle=self.toggle_record,
            on_cycle=self.cycle_mode,
            on_paste=self.paste_last,
        )

    # ---------- menú ----------
    def _build_menu(self):
        items = []
        for key, info in modes.modes_by_key().items():
            mi = rumps.MenuItem(info["label"], callback=self._make_mode_cb(key))
            mi.state = 1 if key == self.mode else 0
            items.append(mi)
        self.mode_items = {key: mi for (key, _), mi in zip(modes.modes_by_key().items(), items)}

        self.status = rumps.MenuItem("Listo", callback=None)
        self.test = rumps.MenuItem("Probar dictado (3s)", callback=self.test_dictation)
        self.health = rumps.MenuItem("Estado backends…", callback=self.show_health)
        self.quit = rumps.MenuItem("Salir", callback=self._quit)

        self.menu = [
            *items,
            rumps.separator,
            self.status,
            self.test,
            self.health,
            rumps.separator,
            self.quit,
        ]
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
        label = modes.MODES.get(self.mode, {}).get("label", "Dictador")
        self.title = f"🎙 {label}"
        self.status.title = f"Modo: {label} · {self._state}"

    # ---------- grabación ----------
    def toggle_record(self):
        with self._lock:
            state = self._state
        if state == "IDLE":
            self._start_record()
        elif state == "RECORDING":
            self._stop_record(force=True)

    def _start_record(self):
        with self._lock:
            self._state = "RECORDING"
        self._refresh_title()
        acfg = audio.AudioConfig(
            device=self.cfg.get("audio.device"),
            vad_aggressiveness=self.cfg.get("audio.vad_aggressiveness", 2),
            silence_to_stop=self.cfg.get("audio.silence_to_stop", 1.2),
            max_duration=self.cfg.get("audio.max_duration", 60.0),
            min_duration=self.cfg.get("audio.min_duration", 0.4),
        )
        self._recorder = audio.Recorder(acfg)
        if self._show_overlay:
            self._overlay.show("Escuchando… habla ahora.")
        # hilo de partials: re-transcribe la ventana reciente
        self._partial_running.set()
        self._partial_thread = threading.Thread(target=self._partial_loop, daemon=True)
        self._partial_thread.start()
        self._recorder.start(on_stop=self._on_stop)
        log.info("Grabando…")

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
                if len(a) / audio.SR < 0.4:
                    continue
                text = stt.transcribe(a, self.stt_model, self.stt_lang)
                if text and self._partial_running.is_set():
                    self._overlay.update(text)
            except Exception as e:
                log.debug("partial error: %s", e)

    def _on_stop(self, audio_buf, duration: float):
        self._partial_running.clear()
        with self._lock:
            self._state = "PROCESSING"
        self._refresh_title()
        self._overlay.update("Procesando…")
        threading.Thread(
            target=self._process, args=(audio_buf, duration), daemon=True
        ).start()

    def _process(self, audio_buf, duration):
        try:
            if audio_buf is None or len(audio_buf) == 0:
                log.info("Grabación descartada (muy corta).")
                self._reset_idle()
                return
            # 1) transcripción final
            transcript = stt.transcribe(audio_buf, self.stt_model, self.stt_lang)
            log.info("Transcripción: %s", transcript)
            if not transcript:
                self._overlay.update("(no se detectó voz)")
                time.sleep(1.2)
                self._reset_idle()
                return
            # 2) refino por modo
            refiner = refine.Refiner(self.cfg)
            final = refiner.refine(transcript, self.mode, self.language)
            if not final:
                final = transcript
            self._last_result = final
            log.info("Final: %s", final)
            # 3) entregar
            auto_paste = bool(self.cfg.get("output.auto_paste", True))
            copy = bool(self.cfg.get("output.copy_to_clipboard", True))
            output.deliver(final, auto_paste=auto_paste, copy=copy)
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

    # ---------- acciones de menú ----------
    def test_dictation(self, _sender):
        if self._state != "IDLE":
            rumps.notification("Dictador", "Ocupado", "Ya hay una grabación en curso")
            return
        rumps.notification("Dictador", "Prueba", "Pulsa F5 o el botón para dictar ahora.")
        self.toggle_record()

    def paste_last(self):
        if self._last_result:
            output.copy_to_clipboard(self._last_result)
            output.paste_frontmost()

    def show_health(self, _sender):
        h = refine.health()
        msg = " · ".join(f"{k}: {'✓' if v else '✗'}" for k, v in h.items())
        rumps.notification("Dictador", "Backends", msg)
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
        # arranca whisper-server en background para que el primer dictado no pague el coste
        threading.Thread(target=self._warmup, daemon=True).start()
        self._hotkey.start()
        super().run()

    def _warmup(self):
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