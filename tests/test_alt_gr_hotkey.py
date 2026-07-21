"""alt_gr es, en macOS, la MISMA tecla física que alt_r — pynput colapsa
Key.alt_gr en Key.alt_r (mismo virtual keycode, enum.Enum los une en un solo
miembro; verificado contra el pynput del proyecto: `Key.alt_gr is Key.alt_r`
y `Key.alt_gr.name == "alt_r"`).

Antes de este fix, configurar alt_gr como tecla de dictado la dejaba muda:
_canon() no la traducía, así que la tecla configurada ("alt_gr") nunca casaba
con el nombre que el teclado reporta de verdad ("alt_r") y la grabación no
arrancaba jamás — sin error, sin log, nada.
"""
import threading

from pynput import keyboard

from voooxly.hotkey import HotkeyManager


def _mk(on_start, on_stop, guard=False):
    return HotkeyManager(
        toggle_mode="hold",
        toggle_keys=["alt_gr"],
        cycle_keys=["ctrl", "shift", "m"],
        paste_keys=["ctrl", "shift", "v"],
        on_toggle=lambda: None,
        on_start=on_start,
        on_stop=on_stop,
        on_cycle=lambda: None,
        on_paste=lambda: None,
        cancel_keys=["esc"],
        on_cancel=lambda: None,
        toggle_guard=guard,
    )


def test_alt_gr_configurado_arranca_con_la_tecla_que_pynput_reporta_de_verdad():
    # Lo que pulsa el usuario es la tecla física AltGr/Option derecha; lo que
    # pynput entrega al listener es keyboard.Key.alt_r. Sin la traducción en
    # _canon, esta pulsación nunca casaba con "alt_gr" y no pasaba nada.
    started = threading.Event()
    hk = _mk(started.set, lambda: None)
    hk._on_press(keyboard.Key.alt_r)
    assert started.wait(2.0), "alt_gr configurado no arrancó con la tecla real (alt_r)"


def test_alt_gr_para_al_soltar():
    started, stopped = threading.Event(), threading.Event()
    hk = _mk(started.set, stopped.set)
    hk._on_press(keyboard.Key.alt_r)
    assert started.wait(2.0)
    hk._on_release(keyboard.Key.alt_r)
    assert stopped.wait(2.0)
