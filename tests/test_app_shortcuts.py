"""El pegamento entre la ventana y el hotkey, sin instanciar VoooxlyApp.

Instanciar VoooxlyApp construye menús de AppKit y no corre en un test (mismo
motivo por el que existen keys.py, shortcuts.py y ai_menu_labels a nivel de
módulo). Se prueba la función de aplicar un atajo contra un hotkey falso, y la
función que migra + persiste prefs.json en __init__.
"""
from voooxly import app as app_mod
from voooxly.app import apply_shortcut


class _HotkeyFalso:
    def __init__(self, ok=True):
        self._ok = ok
        self.reconfigurado = None
        self.rebindeado = []
        # Vigilan la regla del sistema (ver test_aplicar_un_atajo_no_reinicia_el_listener
        # más abajo): reconfigure()/rebind() solo pueden mutar atributos, jamás
        # tocar el keyboard.Listener en marcha.
        self.parada = False
        self.arrancada = False

    def reconfigure(self, toggle_key, toggle_mode, guard, guard_delay=None):
        self.reconfigurado = (toggle_key, toggle_mode, guard, guard_delay)
        return self._ok

    def rebind(self, sid, names):
        self.rebindeado.append((sid, names))
        return self._ok

    def stop(self):
        self.parada = True

    def start(self):
        self.arrancada = True


def test_dictation_va_por_reconfigure_con_el_delay_en_segundos():
    hk = _HotkeyFalso()
    ok, msg = apply_shortcut(hk, "dictation", {"keys": ["cmd_l"], "style": "hold", "delay_ms": 400})
    assert ok, msg
    tecla, modo, guarda, delay = hk.reconfigurado
    assert tecla == "cmd_l"
    assert modo == "hold"
    assert guarda is True
    assert abs(delay - 0.4) < 1e-9, "el hotkey espera SEGUNDOS, la ventana da ms"


def test_los_otros_atajos_van_por_rebind():
    hk = _HotkeyFalso()
    ok, _ = apply_shortcut(hk, "cancel", {"keys": ["f13"]})
    assert ok
    assert hk.rebindeado == [("cancel", ["f13"])]


def test_si_el_hotkey_rechaza_se_devuelve_el_motivo():
    hk = _HotkeyFalso(ok=False)
    ok, msg = apply_shortcut(hk, "cancel", {"keys": ["f13"]})
    assert not ok
    assert msg, "un rechazo sin motivo deja al usuario sin saber qué pasó"


def test_una_excepcion_del_hotkey_no_propaga():
    # apply_shortcut lo llama código de AppKit: una excepción sin capturar
    # ahí se lleva la app entera por delante.
    class Explota:
        def reconfigure(self, **kw):
            raise RuntimeError("boom")

    ok, msg = apply_shortcut(Explota(), "dictation",
                             {"keys": ["cmd_r"], "style": "hold", "delay_ms": 0})
    assert not ok
    assert msg


def test_aplicar_un_atajo_no_reinicia_el_listener():
    """Regla del sistema, no detalle de reconfigure()/rebind(): cambiar
    CUALQUIERA de los cuatro atajos jamás llama a .stop() ni a .start()
    sobre el HotkeyManager.

    Reiniciar el keyboard.Listener de pynput reventó la app de verdad con
    SIGTRAP en dispatch_assert_queue (arranca con `with keycode_context()`,
    que toca TIS/TSM desde el hilo del propio listener, y HIToolbox exige
    que eso pase en el hilo principal). Y aunque el hilo fuera el correcto,
    tener dos listeners vivos a la vez — el viejo aún sin unir y el nuevo —
    aborta el proceso con SIGABRT: ambos llamarían a TIS/TSM desde hilos
    distintos. reconfigure() y rebind() lo evitan de raíz: solo mutan
    atributos normales que _on_press/_on_release releen en cada evento, así
    que jamás hace falta recrear el listener (ver sus docstrings en
    hotkey.py). Este test deja esa regla vigilada: si algún día
    apply_shortcut() empieza a llamar a hk.stop()/hk.start(), tiene que
    fallar señalando el crash que evita, no con un AttributeError que el
    `except Exception` de apply_shortcut se traga y disfraza de un
    ok=False genérico.
    """
    hk = _HotkeyFalso()
    filas = {
        "dictation": {"keys": ["cmd_l"], "style": "hold", "delay_ms": 400},
        "cycle_mode": {"keys": ["f13"]},
        "latch": {"keys": ["f14"]},
        "cancel": {"keys": ["f15"]},
    }
    for sid, fila in filas.items():
        ok, msg = apply_shortcut(hk, sid, fila)
        assert ok, msg

    assert not hk.parada, (
        "apply_shortcut() paró el listener: reiniciarlo revienta la app con "
        "SIGTRAP en dispatch_assert_queue. Cambiar un atajo nunca debe tocar "
        "stop()."
    )
    assert not hk.arrancada, (
        "apply_shortcut() arrancó un listener nuevo: con el anterior aún "
        "vivo, dos keyboard.Listener a la vez abortan el proceso con "
        "SIGABRT (HIToolbox: la Text Input Sources API llamada desde dos "
        "hilos a la vez). Cambiar un atajo nunca debe tocar start()."
    )


def test_una_migracion_vieja_acaba_persistida(monkeypatch):
    """Quien actualiza desde v1.3.0 y nunca abre la ventana de Shortcuts
    tiene que acabar con la clave "shortcuts" en su prefs.json igualmente —
    si no, el día que una versión futura deje de leer las claves viejas,
    pierde su configuración sin haber hecho nada malo."""
    guardado = {}
    monkeypatch.setattr(app_mod, "_save_prefs", lambda prefs: guardado.update(prefs))

    prefs = {"dictation_key": "alt_r", "dictation_mode": "toggle"}
    assert app_mod._migrate_shortcuts_prefs(prefs) is True
    assert guardado.get("shortcuts", {}).get("dictation", {}).get("keys") == ["alt_r"]


def test_un_prefs_ya_migrado_no_provoca_escritura(monkeypatch):
    """Sin este corte, __init__ reescribiría prefs.json en cada arranque sin
    motivo — shortcuts.migrate() ya no tiene nada que cambiar aquí."""
    llamadas = []
    monkeypatch.setattr(app_mod, "_save_prefs", lambda prefs: llamadas.append(prefs))

    prefs = {
        "dictation_key": "alt_r",
        "shortcuts": {"dictation": {"keys": ["f13"], "delay_ms": 0, "style": "hold"}},
    }
    assert app_mod._migrate_shortcuts_prefs(prefs) is False
    assert llamadas == []
