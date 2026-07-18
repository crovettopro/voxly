"""Hotkeys globales con pynput. Requiere permiso de Accesibilidad en macOS.

IMPORTANTE: usamos UN SOLO keyboard.Listener para todo. Si se arrancan varios
listeners (p.ej. GlobalHotKeys + Listener), cada uno llama a TIS/TSM desde su
propio hilo y HIToolbox aborta el proceso con SIGABRT ("Text Input Sources API
is being called in two threads concurrently"). Un único listener evita la carrera.

Modos del botón de dictado:
- "hold"  (push-to-talk, estilo Wispr): mantienes pulsada la tecla para hablar,
  la sueltas para terminar.
- "toggle": pulsas para empezar, pulsas/te callas para terminar.

cycle_mode (Ctrl+Shift+M) y paste_last (Ctrl+Shift+V) se detectan como combos
dentro del mismo listener.

cancel (Esc) descarta el dictado en curso: la app decide si aplica (solo cuando
está grabando o procesando), así que dispararlo en cada Esc del sistema es barato.
"""
from __future__ import annotations

import logging
import threading

from pynput import keyboard

log = logging.getLogger("dictador.hotkey")


def _norm(key) -> str:
    """Normaliza una tecla pynput a un nombre lowercase estable."""
    if isinstance(key, keyboard.KeyCode):
        if key.char:
            return key.char.lower()
        # teclas virtuales sin char (raro en mac)
        return ""
    name = getattr(key, "name", "").lower()
    # unificar cmd/cmd_l/cmd_r para combos pero conservar cmd_r para hold
    return name


def _combo_names(keys: list[str]) -> frozenset[str]:
    return frozenset(k.lower() for k in keys)


class HotkeyManager:
    def __init__(
        self,
        toggle_mode: str,
        toggle_keys: list[str],
        cycle_keys: list[str],
        paste_keys: list[str],
        on_toggle,
        on_start,
        on_stop,
        on_cycle,
        on_paste,
        cancel_keys: list[str] | None = None,
        on_cancel=None,
    ):
        self.toggle_mode = toggle_mode
        self.on_toggle = on_toggle
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_cycle = on_cycle
        self.on_paste = on_paste
        self.on_cancel = on_cancel

        # tecla de dictado (modo hold: una sola tecla)
        self._toggle_key = toggle_keys[0].lower() if toggle_keys else None
        # tecla de cancelar (una sola, Esc por defecto)
        self._cancel_key = cancel_keys[0].lower() if cancel_keys else None
        self._held = False
        # combos (cycle/paste) y también el toggle si modo "toggle" con combo
        self._cycle_combo = _combo_names(cycle_keys) if cycle_keys else None
        self._paste_combo = _combo_names(paste_keys) if paste_keys else None
        self._toggle_combo = _combo_names(toggle_keys) if (toggle_mode != "hold" and toggle_keys) else None

        self._pressed: set[str] = set()
        self._pressed_lock = threading.Lock()
        self._listener: keyboard.Listener | None = None

    # --- listener callbacks ---
    def _on_press(self, key):
        name = _norm(key)
        if not name:
            return
        with self._pressed_lock:
            already = name in self._pressed
            self._pressed.add(name)
            snapshot = frozenset(self._pressed)

        # --- dictado ---
        if self.toggle_mode == "hold" and name == self._toggle_key:
            if not self._held:
                self._held = True
                threading.Thread(target=self.on_start, daemon=True).start()
            return

        if already:
            return  # autorepeat: no re-disparar combos ni el cancel

        # --- cancelar dictado (Esc) ---
        if self.on_cancel and name == self._cancel_key:
            threading.Thread(target=self.on_cancel, daemon=True).start()
            return

        # --- combos (incluye toggle en modo toggle si es combo) ---
        if self._toggle_combo and snapshot == self._toggle_combo:
            threading.Thread(target=self.on_toggle, daemon=True).start()
            return
        if self._cycle_combo and snapshot == self._cycle_combo:
            threading.Thread(target=self.on_cycle, daemon=True).start()
            return
        if self._paste_combo and snapshot == self._paste_combo:
            threading.Thread(target=self.on_paste, daemon=True).start()
            return

    def _on_release(self, key):
        name = _norm(key)
        if not name:
            return
        with self._pressed_lock:
            self._pressed.discard(name)

        if self.toggle_mode == "hold" and name == self._toggle_key and self._held:
            self._held = False
            threading.Thread(target=self.on_stop, daemon=True).start()

    def start(self) -> None:
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()
        log.info("Hotkeys activos (modo %s, tecla dictado: %s).", self.toggle_mode, self._toggle_key)

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None