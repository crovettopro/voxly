"""reconfigure() no puede fiarse de que quien llama ya pasó por
keys.resolve/validate_custom. Hoy esa colisión la evita keys._RESERVADAS
(shift y shift_l están las dos ahí), pero eso solo protege al camino que pasa
por esa puerta. Una tarea que llama a reconfigure() directo desde el menú se
la salta entera, así que reconfigure() tiene que defenderse por su cuenta.

Sin este chequeo, reconfigure(toggle_key="shift_l", ...) deja _toggle_key ==
_latch_key == "shift": el shift pasa a ser la tecla de dictado Y la de latch
a la vez, el latch queda muerto (el `return` de la rama hold del propio
dictado nunca deja llegar al bloque de latch) y el shift derecho fija en
silencio en vez de dictar.

"Rechazar" aquí significa devolver False y dejar la configuración anterior
intacta — NO levantar una excepción. Quien llama es código de menú de
AppKit: una excepción sin capturar ahí se lleva la app entera por delante
por culpa de una tecla mal elegida.
"""
import threading

from pynput import keyboard

from voooxly.hotkey import HotkeyManager


def _mk():
    return HotkeyManager(
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
    )


def test_shift_l_como_tecla_de_dictado_se_rechaza_por_colisionar_con_latch():
    # shift_l canonicaliza a "shift" (Key.shift_l is Key.shift en macOS),
    # que es también la tecla de latch por defecto.
    hk = _mk()
    ok = hk.reconfigure(toggle_key="shift_l", toggle_mode="hold", guard=True)
    assert ok is False
    assert hk._toggle_key == "cmd_r", "la colisión se aceptó y pisó la tecla anterior"


def test_esc_como_tecla_de_dictado_se_rechaza_por_colisionar_con_cancel():
    hk = _mk()
    ok = hk.reconfigure(toggle_key="esc", toggle_mode="hold", guard=False)
    assert ok is False
    assert hk._toggle_key == "cmd_r"


def test_una_tecla_sin_colision_se_acepta_normalmente():
    hk = _mk()
    ok = hk.reconfigure(toggle_key="f13", toggle_mode="hold", guard=False)
    assert ok is True
    assert hk._toggle_key == "f13"


def test_tras_un_rechazo_la_tecla_anterior_sigue_funcionando():
    # El rechazo no puede dejar el manager en un estado a medias: cmd_r
    # (la tecla vigente antes de la llamada rechazada) tiene que seguir
    # arrancando grabaciones con normalidad.
    started = threading.Event()
    hk = _mk()
    hk.on_start = started.set
    ok = hk.reconfigure(toggle_key="shift_l", toggle_mode="hold", guard=True)
    assert ok is False
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(2.0), "tras el rechazo, la tecla anterior dejó de funcionar"
