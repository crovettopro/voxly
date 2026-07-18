"""Hotkeys globales con pynput. Requiere permiso de Accesibilidad en macOS."""
from __future__ import annotations

import logging
import threading

from pynput import keyboard

log = logging.getLogger("dictador.hotkey")

# mapeo config-string -> token pynput GlobalHotKeys
_TOKENS = {
    "ctrl": "<ctrl>",
    "control": "<ctrl>",
    "shift": "<shift>",
    "cmd": "<cmd>",
    "command": "<cmd>",
    "cmd_r": "<cmd>",
    "cmd_l": "<cmd>",
    "alt": "<alt>",
    "option": "<alt>",
    "space": "<space>",
    "enter": "<enter>",
    "tab": "<tab>",
}


def _to_combo(keys: list[str]) -> str:
    parts = []
    for k in keys:
        kl = k.lower()
        if kl in _TOKENS:
            parts.append(_TOKENS[kl])
        elif kl.startswith("f") and kl[1:].isdigit():
            parts.append(f"<{kl}>")
        elif len(k) == 1:
            # pynput quiere los caracteres normales sin corchetes
            parts.append(k.lower())
        else:
            parts.append(f"<{kl}>")
    return "+".join(parts)


class HotkeyManager:
    def __init__(
        self,
        toggle_keys: list[str],
        cycle_keys: list[str],
        paste_keys: list[str],
        on_toggle,
        on_cycle,
        on_paste,
    ):
        self.on_toggle = on_toggle
        self.on_cycle = on_cycle
        self.on_paste = on_paste
        self._listeners: list = []
        self._thread = None

        combos = {}
        # toggle como combo (soporta tecla simple como F5)
        if toggle_keys:
            combos[_to_combo(toggle_keys)] = self._fire_toggle
        if cycle_keys:
            combos[_to_combo(cycle_keys)] = self._fire_cycle
        if paste_keys:
            combos[_to_combo(paste_keys)] = self._fire_paste

        self._ghk = keyboard.GlobalHotKeys(combos) if combos else None

    def _fire_toggle(self):
        log.debug("hotkey toggle")
        threading.Thread(target=self.on_toggle, daemon=True).start()

    def _fire_cycle(self):
        log.debug("hotkey cycle")
        threading.Thread(target=self.on_cycle, daemon=True).start()

    def _fire_paste(self):
        log.debug("hotkey paste")
        threading.Thread(target=self.on_paste, daemon=True).start()

    def start(self) -> None:
        if self._ghk:
            self._ghk.start()
            log.info("Hotkeys activos.")

    def stop(self) -> None:
        if self._ghk:
            self._ghk.stop()