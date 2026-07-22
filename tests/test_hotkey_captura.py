"""Capturar teclas para la ventana de Shortcuts, sin un segundo listener.

Dos listeners hacen que pynput llame a TIS/TSM desde dos hilos y HIToolbox
aborta el proceso con SIGABRT, así que la captura la sirve el listener que ya
está corriendo: mientras captura, _on_press desvía todo al callback y no
dispara NINGUNA acción. Si dictase mientras el usuario elige tecla, elegir el
⌘ derecho arrancaría una grabación en mitad del ajuste.

El nombre capturado es el mismo que _norm() reportará en runtime. Eso es lo
que hace que la tecla elegida case de verdad: configurar "cmd_l" a mano no
casaba nunca, porque pynput reporta "cmd" (ver el header de hotkey.py).
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


def test_capturando_llega_el_nombre_de_la_tecla():
    visto = []
    hk = _mk()
    hk.begin_capture(visto.append)
    hk._on_press(keyboard.Key.f13)
    assert visto == [["f13"]]


def test_capturando_un_combo_llega_entero_y_en_orden():
    visto = []
    hk = _mk()
    hk.begin_capture(visto.append)
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    hk._on_press(keyboard.KeyCode.from_char("p"))
    assert visto[-1] == ["ctrl", "shift", "p"]


def test_capturando_la_tecla_de_dictado_no_arranca_una_grabacion():
    # El caso que hace la captura obligatoria: elegir ⌘ derecho no puede
    # ponerse a grabar en mitad del ajuste.
    started = threading.Event()
    hk = _mk(on_start=started.set)
    hk.begin_capture(lambda names: None)
    hk._on_press(keyboard.Key.cmd_r)
    time.sleep(DELAY * 3)
    assert not started.is_set(), "capturando arrancó una grabación"


def test_capturando_esc_no_cancela_un_dictado():
    fired = threading.Event()
    hk = _mk(on_cancel=fired.set)
    hk.begin_capture(lambda names: None)
    hk._on_press(keyboard.Key.esc)
    time.sleep(DELAY * 3)
    assert not fired.is_set()


def test_capturando_el_combo_de_ciclar_no_cicla():
    fired = threading.Event()
    hk = _mk(on_cycle=fired.set)
    hk.begin_capture(lambda names: None)
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    hk._on_press(keyboard.KeyCode.from_char("m"))
    time.sleep(DELAY * 3)
    assert not fired.is_set(), "el combo disparó durante la captura"


def test_end_capture_devuelve_el_comportamiento_normal():
    started = threading.Event()
    hk = _mk(on_start=started.set)
    hk.begin_capture(lambda names: None)
    hk.end_capture()
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(1.0), "tras end_capture la tecla de dictado no arrancó"


def test_end_capture_es_idempotente():
    # Cerrar la ventana a mitad de captura llama a end_capture(); volver a
    # llamarlo no puede reventar ni dejar el listener mudo.
    hk = _mk()
    hk.begin_capture(lambda names: None)
    hk.end_capture()
    hk.end_capture()
    assert hk.capturing is False


def test_capturing_refleja_el_estado():
    hk = _mk()
    assert hk.capturing is False
    hk.begin_capture(lambda names: None)
    assert hk.capturing is True
    hk.end_capture()
    assert hk.capturing is False


def test_un_callback_que_revienta_no_deja_el_listener_muerto():
    # El callback es código de AppKit. Si lanza, la app no puede quedarse sin
    # hotkeys para siempre.
    hk = _mk()

    def explota(names):
        raise RuntimeError("boom")

    hk.begin_capture(explota)
    hk._on_press(keyboard.Key.f13)     # no debe propagar
    hk.end_capture()
    assert hk.capturing is False


def test_soltar_teclas_durante_la_captura_no_dispara_nada():
    stopped = threading.Event()
    hk = _mk(on_stop=stopped.set)
    hk.begin_capture(lambda names: None)
    hk._on_press(keyboard.Key.cmd_r)
    hk._on_release(keyboard.Key.cmd_r)
    time.sleep(DELAY * 3)
    assert not stopped.is_set()
