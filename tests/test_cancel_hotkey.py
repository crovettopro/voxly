"""Esc debe disparar on_cancel una sola vez por pulsación (sin autorepeat)
y sin interferir con la tecla de dictado en modo hold."""
import threading

from pynput import keyboard

from dictador.hotkey import HotkeyManager


def _mk(on_cancel, on_start=None, on_stop=None):
    return HotkeyManager(
        toggle_mode="hold",
        toggle_keys=["cmd_r"],
        cycle_keys=["ctrl", "shift", "m"],
        paste_keys=["ctrl", "shift", "v"],
        on_toggle=lambda: None,
        on_start=on_start or (lambda: None),
        on_stop=on_stop or (lambda: None),
        on_cycle=lambda: None,
        on_paste=lambda: None,
        cancel_keys=["esc"],
        on_cancel=on_cancel,
    )


def test_esc_fires_cancel():
    fired = threading.Event()
    hk = _mk(on_cancel=fired.set)
    hk._on_press(keyboard.Key.esc)
    assert fired.wait(2.0), "Esc no disparó on_cancel"


def test_esc_autorepeat_fires_once():
    count = 0
    done = threading.Event()

    def cb():
        nonlocal count
        count += 1
        done.set()

    hk = _mk(on_cancel=cb)
    hk._on_press(keyboard.Key.esc)   # pulsación real
    assert done.wait(2.0)
    hk._on_press(keyboard.Key.esc)   # autorepeat: la tecla sigue en _pressed
    hk._on_press(keyboard.Key.esc)
    # dar margen a hilos espurios antes de contar
    import time

    time.sleep(0.15)
    assert count == 1, f"autorepeat re-disparó el cancel ({count} veces)"


def test_esc_while_holding_dictation_key():
    """Cancelar mientras se mantiene cmd_r: cancel se dispara y la tecla
    de dictado sigue funcionando en la siguiente pulsación."""
    started = threading.Event()
    canceled = threading.Event()
    hk = _mk(on_cancel=canceled.set, on_start=started.set)

    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(2.0)
    hk._on_press(keyboard.Key.esc)
    assert canceled.wait(2.0)
    # soltar ambas y verificar que una nueva pulsación vuelve a arrancar
    hk._on_release(keyboard.Key.esc)
    hk._on_release(keyboard.Key.cmd_r)
    started.clear()
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(2.0), "la tecla de dictado quedó rota tras cancelar"


def test_no_cancel_key_configured():
    """Sin cancel_keys el listener no debe romperse con Esc."""
    hk = HotkeyManager(
        toggle_mode="hold",
        toggle_keys=["cmd_r"],
        cycle_keys=["ctrl", "shift", "m"],
        paste_keys=["ctrl", "shift", "v"],
        on_toggle=lambda: None,
        on_start=lambda: None,
        on_stop=lambda: None,
        on_cycle=lambda: None,
        on_paste=lambda: None,
    )
    hk._on_press(keyboard.Key.esc)  # no debe lanzar
