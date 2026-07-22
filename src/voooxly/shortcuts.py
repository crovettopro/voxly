"""Registro de atajos, su resolucion y sus conflictos.

Un modulo de datos, sin AppKit y sin pynput, por el mismo motivo que keys.py:
instanciar la ventana de Shortcuts construye AppKit y no se puede hacer en un
test. Aqui vive toda la logica que se puede verificar; settings_window.py solo
pinta lo que esto decide.

La resolucion es la parte delicada. config.yaml es el valor de fabrica y
prefs.json lo que eligio el usuario, y ninguno de los dos puede dejar la app
sin atajos: los dos los edita gente a mano y un tipo equivocado es un error de
tecleo, no un caso de laboratorio. Todo lo que no pasa validate_custom cae al
default en silencio, igual que hacia keys.resolve().
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import keys

# Rango del slider de la ventana. El default NO se aplica a todo el mundo: solo
# aparece cuando la tecla elegida necesita guarda (ver _delay_seguro). Poner
# 400 ms de fabrica al cmd derecho le meteria 0,4 s de espera al arranque de
# dictado a todos los usuarios actuales, que perderian las primeras silabas.
DEFAULT_DELAY_MS = 400
MAX_DELAY_MS = 800

DEFAULT_STYLE = "hold"


@dataclass(frozen=True)
class Shortcut:
    id: str                    # API estable, no renombrar
    label: str                 # UI, en ingles
    subtitle: str              # UI, en ingles
    default: tuple[str, ...]   # nombres pynput
    has_delay: bool


# El orden es el de la ventana. Los ids son API estable: se escriben en
# prefs.json y renombrar uno le borra el atajo al usuario en silencio.
SHORTCUTS: dict[str, Shortcut] = {
    "dictation": Shortcut(
        "dictation", "Dictation", "Hold to talk", ("cmd_r",), True),
    "cycle_mode": Shortcut(
        "cycle_mode", "Cycle mode", "Switch to the next mode",
        ("ctrl", "shift", "m"), False),
    "latch": Shortcut(
        "latch", "Latch dictation", "Keep recording hands-free",
        ("shift",), False),
    "cancel": Shortcut(
        "cancel", "Cancel dictation", "Discard what you're saying",
        ("esc",), False),
}

# De donde sale el valor de fabrica de cada atajo en config.yaml.
_RUTA_YAML = {
    "dictation": "hotkeys.toggle",
    "cycle_mode": "hotkeys.cycle_mode",
    "latch": "hotkeys.latch",
    "cancel": "hotkeys.cancel",
}


def _teclas_validas(valor) -> list[str] | None:
    """Es valor una lista de nombres de tecla usable? None si no."""
    if not isinstance(valor, list) or not valor:
        return None
    fuera = []
    for n in valor:
        if not isinstance(n, str):
            return None
        n = n.strip().lower()
        if not n:
            return None
        fuera.append(n)
    # Los combos de multiples teclas (como ctrl+shift+m) se devuelven sin
    # validar: un modificador sin lado como 'ctrl' es ilegal como tecla de
    # dictado suelta (validate_custom lo rechaza) pero perfectamente legitimo
    # en un combo. Solo las teclas individuales necesitan validacion.
    if len(fuera) == 1:
        return fuera if keys.validate_custom(fuera[0])[0] else None
    return fuera


def _delay_seguro(valor, teclas: list[str]) -> int:
    """Delay en ms, recortado al rango y con un default que no rompe nada.

    Si el valor no es usable, el fallback NO es 0: con una tecla que necesita
    guarda, 0 ms significa que cada cmd+C arranca una grabacion. Se cae al
    default (400) cuando hace falta guarda y a 0 cuando no.
    """
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return DEFAULT_DELAY_MS if keys.needs_guard(teclas[0]) else 0
    if isinstance(valor, float) and not math.isfinite(valor):
        return DEFAULT_DELAY_MS if keys.needs_guard(teclas[0]) else 0
    return max(0, min(MAX_DELAY_MS, int(valor)))


def resolve(prefs: dict, cfg) -> dict[str, dict]:
    """Estado efectivo de los cuatro atajos: prefs por encima del YAML.

    Devuelve {sid: {keys: [...]}}, mas delay_ms y style solo en dictation
    (que es el unico con has_delay=True). Los otros tres (cycle_mode, latch, cancel)
    llevan solo keys.
    """
    guardado = prefs.get("shortcuts") if isinstance(prefs, dict) else None
    if not isinstance(guardado, dict):
        guardado = {}

    fuera: dict[str, dict] = {}
    for sid, sc in SHORTCUTS.items():
        teclas = list(sc.default)

        del_yaml = _teclas_validas(cfg.get(_RUTA_YAML[sid], None))
        if del_yaml is not None:
            teclas = del_yaml

        bloque = guardado.get(sid)
        if not isinstance(bloque, dict):
            bloque = {}
        de_prefs = _teclas_validas(bloque.get("keys"))
        if de_prefs is not None:
            teclas = de_prefs

        fila: dict = {"keys": teclas}
        if sc.has_delay:
            fila["delay_ms"] = _delay_seguro(bloque.get("delay_ms"), teclas)
            estilo = bloque.get("style")
            if not isinstance(estilo, str) or estilo not in keys.MODES:
                estilo = cfg.get("hotkeys.toggle_mode", DEFAULT_STYLE)
            if not isinstance(estilo, str) or estilo not in keys.MODES:
                estilo = DEFAULT_STYLE
            fila["style"] = estilo
        fuera[sid] = fila
    return fuera


# El delay que la v1.3.0 aplicaba sin preguntar a las teclas con guarda. NO es
# DEFAULT_DELAY_MS: quien actualiza conserva su tacto de siempre y solo ve 400
# si cambia de tecla desde la ventana nueva.
_DELAY_HEREDADO_MS = 300


def migrate(prefs: dict) -> bool:
    """Traduce el formato de v1.3.0 al bloque shortcuts. Muta prefs.

    Solo migra dictation: los otros tres nunca fueron configurables, asi que
    resolve() ya les da el default correcto sin ayuda.

    Las claves viejas se dejan escritas a proposito. Si el usuario vuelve a
    una version anterior, se las encuentra intactas; y si no vuelve, en dos
    versiones se limpian. Borrarlas aqui haria el downgrade destructivo.
    """
    if not isinstance(prefs, dict):
        return False
    if isinstance(prefs.get("shortcuts"), dict) and prefs["shortcuts"]:
        return False

    tecla = prefs.get("dictation_key")
    if not isinstance(tecla, str) or not keys.validate_custom(tecla)[0]:
        return False

    fila = {
        "keys": [tecla],
        "delay_ms": _DELAY_HEREDADO_MS if keys.needs_guard(tecla) else 0,
    }
    estilo = prefs.get("dictation_mode")
    fila["style"] = estilo if isinstance(estilo, str) and estilo in keys.MODES else DEFAULT_STYLE

    prefs["shortcuts"] = {"dictation": fila}
    return True


def _firma(names: list[str]) -> frozenset[str]:
    """Conjunto canonico de un binding, para comparar dos atajos.

    Canonicalizado a proposito: cmd_l y cmd son la misma tecla fisica en
    macOS y compararlos como strings crudos dejaria pasar la colision.
    """
    return frozenset(keys.canon(n) for n in names)


def validate(sid: str, names: list[str], actuales: dict[str, dict]) -> tuple[bool, str]:
    """Se puede asignar names a sid? Devuelve (ok, mensaje).

    El mensaje va en INGLES: sale tal cual en la fila de la ventana. Cuando
    ok es True el mensaje puede traer un aviso (F5) - es informativo, no un
    rechazo, porque elegir F5 es legitimo aunque sea mala idea.
    """
    if not names:
        return False, "Press the keys you want to use."

    mia = _firma(names)
    for otro_sid, fila in actuales.items():
        if otro_sid == sid or otro_sid not in SHORTCUTS:
            continue
        other_keys = fila.get("keys")
        if other_keys is None:
            other_keys = []
        if _firma(list(other_keys)) == mia:
            label = SHORTCUTS[otro_sid].label
            msg = 'That shortcut is already used by "' + label + '". Pick another one.'
            return False, msg

    if len(names) == 1:
        ok, msg = keys.validate_custom(names[0])
        if not ok:
            return False, msg

    if "f5" in {n.lower() for n in names}:
        msg = "Heads up: F5 is the macOS Dictation key, so macOS may react to it too."
        return True, msg
    return True, ""
