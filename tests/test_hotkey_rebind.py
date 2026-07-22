"""Cambiar los atajos que NO son el de dictado, en caliente.

Hasta ahora cycle/latch/cancel se fijaban en el constructor y solo se movían
editando config.yaml. La ventana de Shortcuts los cambia con el listener ya
corriendo, así que rebind() tiene que aplicarse sin recrear nada: recrear el
listener es lo que mata la app (dos listeners → SIGABRT en HIToolbox).
"""
import threading
import time

from pynput import keyboard

from voooxly.hotkey import HotkeyManager

DELAY = 0.05


def _mk(**cbs):
    base = dict(
        toggle_mode="hold",
        toggle_keys=["cmd_r"],
        cycle_keys=["ctrl", "shift", "m"],
        on_toggle=lambda: None,
        on_start=lambda: None,
        on_stop=lambda: None,
        on_cycle=lambda: None,
        cancel_keys=["esc"],
        on_cancel=lambda: None,
        latch_keys=["shift"],
        on_latch=lambda: None,
        toggle_guard=False,
        guard_delay=DELAY,
    )
    base.update(cbs)
    return HotkeyManager(**base)


def test_rebind_cambia_el_combo_de_cycle():
    fired = threading.Event()
    hk = _mk(on_cycle=fired.set)
    assert hk.rebind("cycle_mode", ["ctrl", "shift", "p"]) is True
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    hk._on_press(keyboard.KeyCode.from_char("p"))
    assert fired.wait(1.0), "el combo nuevo no disparó"


def test_rebind_deja_muerto_el_combo_viejo():
    fired = threading.Event()
    hk = _mk(on_cycle=fired.set)
    hk.rebind("cycle_mode", ["ctrl", "shift", "p"])
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    hk._on_press(keyboard.KeyCode.from_char("m"))
    time.sleep(DELAY * 3)
    assert not fired.is_set(), "el combo viejo seguía vivo"


def test_rebind_cambia_la_tecla_de_cancelar():
    fired = threading.Event()
    hk = _mk(on_cancel=fired.set)
    assert hk.rebind("cancel", ["f13"]) is True
    hk._on_press(keyboard.Key.f13)
    assert fired.wait(1.0)


def test_rebind_cambia_la_tecla_de_latch():
    started, latched = threading.Event(), threading.Event()
    hk = _mk(on_start=started.set, on_latch=latched.set)
    assert hk.rebind("latch", ["f14"]) is True
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(1.0)
    hk._on_press(keyboard.Key.f14)
    assert latched.wait(1.0)


def test_rebind_rechaza_la_tecla_de_dictado():
    # Si latch pasa a ser la tecla de dictado, el latch queda muerto: la rama
    # de hold retorna antes de llegar a él. Es el fallo mudo de siempre.
    hk = _mk()
    assert hk.rebind("latch", ["cmd_r"]) is False


def test_rebind_rechaza_un_id_desconocido():
    hk = _mk()
    assert hk.rebind("dictation", ["f13"]) is False


def test_reconfigure_cambia_el_delay_en_caliente():
    # El slíder de la ventana: bajar el delay tiene que notarse sin reiniciar.
    started = threading.Event()
    hk = _mk(on_start=started.set, toggle_guard=True)
    hk.reconfigure(toggle_key="cmd_r", toggle_mode="hold", guard=True, guard_delay=0.01)
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(1.0)
    assert hk._guard_delay == 0.01


def test_reconfigure_sin_delay_conserva_el_actual():
    hk = _mk()
    hk.reconfigure(toggle_key="cmd_r", toggle_mode="hold", guard=False)
    assert hk._guard_delay == DELAY
