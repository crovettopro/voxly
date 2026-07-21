"""_restart_hotkey lee resultado["ok"] justo después de llamar a self._on_main
(apply). Eso solo es seguro si _on_main ejecuta apply() de forma SÍNCRONA, y
_on_main.__doc__ dice que eso pasa únicamente en el hilo principal — fuera de
él, AppHelper.callAfter es asíncrono: apply() correría más tarde, en otro
momento, y resultado["ok"] seguiría en su valor inicial (False) aunque la
tecla SÍ haya cambiado de verdad. Eso deja `_dictation_key`/el checkmark del
menú desincronizados de lo que el hotkey tiene realmente activo, y encima
persiste sin que _set_dictation_key se entere de que sí funcionó (no guarda
prefs.json porque cree que reconfigure() falló).

Hoy solo llegan a _restart_hotkey callbacks de rumps, que ya corren en el
hilo principal — el invariante se cumplía por construcción, pero nada lo
hacía explícito ni saltaba si alguna vez dejara de cumplirse (p.ej. un
callback nuevo disparado desde un hilo de fondo, como los que sí necesitan
_on_main en el resto de app.py). Fix 5: un assert lo deja explícito.

No se instancia VoooxlyApp (construye menús AppKit reales — no se puede
hacer en un test, ver docstring de keys.py); se llama al método sin ligar a
una instancia real, con un doble mínimo que solo expone lo que
_restart_hotkey toca.
"""
from __future__ import annotations

import threading

from voooxly.app import VoooxlyApp


class _HotkeyFalso:
    def __init__(self):
        self.parada = False
        self.arrancada = False

    def stop(self):
        self.parada = True

    def start(self):
        self.arrancada = True

    def reconfigure(self, toggle_key, toggle_mode, guard):
        return True


class _AppFalsa:
    """Doble mínimo: solo lo que _restart_hotkey lee o escribe."""

    def __init__(self):
        self._hotkey = _HotkeyFalso()
        self._dictation_key = "cmd_r"
        self._toggle_mode = "hold"
        self.key_items = {}
        self.style_items = {}

    def _on_main(self, fn):
        # Igual que el _on_main real en el hilo principal: síncrono.
        fn()


def test_restart_hotkey_exige_el_hilo_principal():
    fake = _AppFalsa()
    disparado = {"assertion": False}

    def worker():
        try:
            VoooxlyApp._restart_hotkey(fake, "f13", "hold")
        except AssertionError:
            disparado["assertion"] = True

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=2.0)
    assert disparado["assertion"], (
        "_restart_hotkey no exige estar en el hilo principal: llamado desde "
        "un hilo de fondo, AppHelper.callAfter sería async y resultado[\"ok\"] "
        "se leería antes de que apply() corriera de verdad"
    )


def test_restart_hotkey_funciona_normal_en_el_hilo_principal():
    fake = _AppFalsa()
    aplicado = VoooxlyApp._restart_hotkey(fake, "alt_r", "hold")
    assert aplicado is True
    assert fake._dictation_key == "alt_r"


def test_cambiar_de_tecla_NO_rearranca_el_listener():
    """El rearranque mataba la app con SIGTRAP.

    pynput arranca su listener con `with keycode_context()` (_darwin.py:272),
    que llama a TISGetInputSourceProperty DESDE EL HILO DEL LISTENER. macOS
    exige que las APIs de fuentes de entrada vayan por el hilo principal, pero
    solo lo verifica cuando tiene que reconstruir la lista — normalmente está
    cacheada y no pasa nada. Pulsar F5 (la tecla de Dictado del sistema en un
    Mac) cambia la fuente de entrada e invalida esa caché: el siguiente
    arranque del listener la reconstruye desde el hilo equivocado y HIToolbox
    mata el proceso con SIGTRAP en dispatch_assert_queue.

    Y el rearranque nunca hizo falta: reconfigure() solo toca atributos
    normales, y _on_press/_on_release los leen en cada evento. Su propio
    docstring dice "sin recrear el manager".
    """
    fake = _AppFalsa()
    VoooxlyApp._restart_hotkey(fake, "alt_r", "hold")
    assert fake._hotkey.parada is False, "stop() re-entra en keycode_context() al volver a start()"
    assert fake._hotkey.arrancada is False, "start() llama a TIS/TSM desde el hilo del listener"
