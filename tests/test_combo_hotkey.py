"""Ctrl+Shift+M (ciclo de modos) TIENE que casar en macOS, donde pynput
entrega la letra como carácter de control cuando Ctrl está pulsado
(Ctrl+M = '\\r'). El bug original comparaba chars crudos y el combo no
disparaba jamás.
"""
import threading

from pynput import keyboard

from voooxly.hotkey import HotkeyManager


def _mk(on_cycle=None):
    return HotkeyManager(
        toggle_mode="hold",
        toggle_keys=["cmd_r"],
        cycle_keys=["ctrl", "shift", "m"],
        on_toggle=lambda: None,
        on_start=lambda: None,
        on_stop=lambda: None,
        on_cycle=on_cycle or (lambda: None),
        cancel_keys=["esc"],
        on_cancel=lambda: None,
    )


def test_ctrl_shift_m_con_control_char_dispara_cycle():
    """Lo que macOS entrega de verdad al pulsar Ctrl+Shift+M."""
    fired = threading.Event()
    hk = _mk(on_cycle=fired.set)
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    hk._on_press(keyboard.KeyCode(char="\r", vk=46))  # Ctrl+M llega como \r
    assert fired.wait(2.0), "ctrl+shift+m no disparó el ciclo de modos"


def test_char_limpio_sigue_funcionando():
    """Por si algún backend entrega la letra sin mapear a control char."""
    fired = threading.Event()
    hk = _mk(on_cycle=fired.set)
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    hk._on_press(keyboard.KeyCode.from_char("M"))  # mayúscula por el shift
    assert fired.wait(2.0)


def test_sin_char_cae_al_virtual_keycode():
    fired = threading.Event()
    hk = _mk(on_cycle=fired.set)
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    hk._on_press(keyboard.KeyCode(vk=46))  # sin char: solo el vk de la M
    assert fired.wait(2.0)


def test_el_combo_exige_las_tres_teclas():
    fired = threading.Event()
    hk = _mk(on_cycle=fired.set)
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.KeyCode(char="\r", vk=46))  # falta shift
    import time

    time.sleep(0.15)
    assert not fired.is_set()
