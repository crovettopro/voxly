"""Registro de atajos, su resolución y sus conflictos.

Un módulo de datos, sin AppKit y sin pynput, por el mismo motivo que keys.py:
instanciar la ventana de Shortcuts construye AppKit y no se puede hacer en un
test. Aquí vive toda la lógica que se puede verificar; settings_window.py solo
pinta lo que esto decide.

La resolución es la parte delicada. config.yaml es el valor de fábrica y
prefs.json lo que eligió el usuario, y ninguno de los dos puede dejar la app
sin atajos: los dos los edita gente a mano y un tipo equivocado es un error de
tecleo, no un caso de laboratorio. Todo lo que no pasa validate_custom cae al
default en silencio, igual que hacía keys.resolve().
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import keys

# Rango del slíder de la ventana. El default NO se aplica a todo el mundo: solo
# aparece cuando la tecla elegida necesita guarda (ver _delay_seguro). Poner
# 400 ms de fábrica al ⌘ derecho le metería 0,4 s de espera al arranque de
# dictado a todos los usuarios actuales, que perderían las primeras sílabas.
DEFAULT_DELAY_MS = 400
MAX_DELAY_MS = 800

DEFAULT_STYLE = "hold"


@dataclass(frozen=True)
class Shortcut:
    id: str                    # API estable, no renombrar
    label: str                 # UI, en inglés
    subtitle: str              # UI, en inglés
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

# De dónde sale el valor de fábrica de cada atajo en config.yaml.
_RUTA_YAML = {
    "dictation": "hotkeys.toggle",
    "cycle_mode": "hotkeys.cycle_mode",
    "latch": "hotkeys.latch",
    "cancel": "hotkeys.cancel",
}


def _teclas_validas(valor) -> list[str] | None:
    """¿`valor` es una lista de nombres de tecla usable? None si no."""
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
    # Los combos de múltiples teclas (como ctrl+shift+m) se devuelven sin
    # validar: un modificador sin lado como 'ctrl' es ilegal como tecla de
    # dictado suelta (validate_custom lo rechaza) pero perfectamente legítimo
    # en un combo. Solo las teclas individuales necesitan validación.
    if len(fuera) == 1:
        return fuera if keys.validate_custom(fuera[0])[0] else None
    return fuera


def _delay_seguro(valor, teclas: list[str]) -> int:
    """Delay en ms, recortado al rango y con un default que no rompe nada.

    Si el valor no es usable, el fallback NO es 0: con una tecla que necesita
    guarda, 0 ms significa que cada ⌘C arranca una grabación. Se cae al
    default (400) cuando hace falta guarda y a 0 cuando no.
    """
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return DEFAULT_DELAY_MS if keys.needs_guard(teclas[0]) else 0
    if isinstance(valor, float) and not math.isfinite(valor):
        return DEFAULT_DELAY_MS if keys.needs_guard(teclas[0]) else 0
    return max(0, min(MAX_DELAY_MS, int(valor)))


def resolve(prefs: dict, cfg) -> dict[str, dict]:
    """Estado efectivo de los cuatro atajos: prefs por encima del YAML.

    Devuelve {sid: {"keys": [...]}}, más "delay_ms" y "style" solo en dictation
    (que es el único con has_delay=True). Los otros tres (cycle_mode, latch, cancel)
    llevan solo "keys".
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
    """Traduce el formato de v1.3.0 al bloque `shortcuts`. Muta `prefs`.

    Solo migra `dictation`: los otros tres nunca fueron configurables, así que
    resolve() ya les da el default correcto sin ayuda.

    Las claves viejas se dejan escritas a propósito. Si el usuario vuelve a
    una versión anterior, se las encuentra intactas; y si no vuelve, en dos
    versiones se limpian. Borrarlas aquí haría el downgrade destructivo.
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


# Nombres pynput SIN lado: son la IZQUIERDA (pynput colapsa cmd_l/alt_l/
# ctrl_l/shift_l en el nombre plano, ver keys._ALIAS_IZQUIERDA) — pero en el
# atajo latch también ensanchan a la derecha, porque hotkey.py:421 casa por
# PREFIJO (`name.startswith(self._latch_key + "_")`) y no por igualdad.
_MODIFICADORES_SIN_LADO = {"cmd", "alt", "ctrl", "shift"}

# Nombres pynput que identifican la tecla derecha sin ambigüedad posible: no
# existe un "<nombre>_r_algo" con el que el prefijo de latch pueda seguir
# ensanchando, así que estos casan un único lado pase lo que pase el atajo.
_MODIFICADORES_DERECHA = {"cmd_r", "alt_r", "ctrl_r", "shift_r"}


def matched_keys(sid: str, names: list[str]) -> set[str]:
    """Nombres canónicos de las teclas FÍSICAS que `hotkey.py` casa de
    verdad en runtime para el atajo `sid` con `names` como binding actual.

    Es el hecho único del que derivan tanto `side_hint()` (lo resume en una
    palabra para la fila) como `lit_keys()` de settings_window.py (enciende
    casillas con él): antes cada uno lo recalculaba a su manera y se podían
    desincronizar — el bug real de la Task 9, con "shift" encendido en el
    teclado y "shift_r" apagado mientras la fila decía "either side".

    Cada nombre de `names` se traduce por separado con `keys.canon()`. Un
    combo (len(names) != 1, como el ctrl+shift+m de cycle_mode) no ensancha
    nada: hotkey.py:439 compara el conjunto de teclas pulsadas por IGUALDAD
    exacta con el combo (`_combo_names`), no por prefijo, así que cada tecla
    del combo casa solo su propio lado.

    Con una tecla suelta (len(names) == 1), `latch` es el único que
    ensancha: hotkey.py:421 casa por PREFIJO
    (`name == self._latch_key or name.startswith(self._latch_key + "_")`).
    Ese prefijo solo alarga el resultado cuando la tecla configurada es uno
    de los cuatro modificadores SIN lado (`_MODIFICADORES_SIN_LADO`): el
    único sufijo que pynput reporta de verdad para esos cuatro nombres es
    "_r" (la izquierda ya llega colapsada en el nombre sin lado — ver
    `keys._ALIAS_IZQUIERDA` — así que nunca hay un "<nombre>_l" que casar).
    Una tecla que ya tiene lado propio (p.ej. cmd_r) no ensancha nada: no
    existe un "cmd_r_algo" con el que el prefijo pueda seguir alargando.
    Los otros tres atajos (dictation, cancel, cycle_mode de una sola tecla)
    casan por igualdad exacta (hotkey.py:397 y :432), así que nunca ensanchan
    pase lo que pase el nombre.
    """
    fuera: set[str] = set()
    for n in names:
        canon = keys.canon(n)
        if not canon:
            continue
        fuera.add(canon)
        if sid == "latch" and len(names) == 1 and canon in _MODIFICADORES_SIN_LADO:
            fuera.add(canon + "_r")
    return fuera


def side_hint(sid: str, names: list[str]) -> str:
    """'right' / 'left' / 'either side' / '' — qué lado(s) de la tecla casan
    de VERDAD en runtime para el atajo `sid`, con `names` como binding actual.

    Vive aquí y no en settings_window.py porque es una decisión sobre
    semántica de atajos (qué hace hotkey.py con este nombre), no de pintado.
    Deriva de `matched_keys()`: no repite su lógica de ensanchado, solo
    traduce el CONJUNTO que esa función calcula a la palabra que se lee en
    la fila. Así las dos vistas -el texto de la fila y las casillas
    encendidas del teclado- son necesariamente la misma verdad.

    Un combo (len(names) != 1) no tiene lado: son varias teclas a la vez y
    ninguna combinación de manos es "la" respuesta — cycle_mode con su
    ctrl+shift+m de fábrica cae aquí.

    Una tecla suelta que no es ni un modificador sin lado ni uno con lado
    propio (una letra, "esc", una F) no tiene lado que anunciar: "".
    """
    if len(names) != 1:
        return ""
    nombre = keys.canon(names[0])
    if nombre not in _MODIFICADORES_SIN_LADO and nombre not in _MODIFICADORES_DERECHA:
        return ""
    if len(matched_keys(sid, names)) > 1:
        return "either side"
    return "right" if nombre in _MODIFICADORES_DERECHA else "left"


def _firma(names: list[str]) -> frozenset[str]:
    """Conjunto canónico de un binding, para comparar dos atajos.

    Canonicalizado a propósito: cmd_l y cmd son la misma tecla física en
    macOS y compararlos como strings crudos dejaría pasar la colisión.
    """
    return frozenset(keys.canon(n) for n in names)


def validate(sid: str, names: list[str], actuales: dict[str, dict]) -> tuple[bool, str]:
    """¿Se puede asignar `names` a `sid`? Devuelve (ok, mensaje).

    El mensaje va en INGLÉS: sale tal cual en la fila de la ventana. Cuando
    ok es True el mensaje puede traer un aviso (F5) - es informativo, no un
    rechazo, porque elegir F5 es legítimo aunque sea mala idea.
    """
    if not names:
        return False, "Press the keys you want to use."

    mia = _firma(names)
    for otro_sid, fila in actuales.items():
        if otro_sid == sid or otro_sid not in SHORTCUTS:
            continue
        other_keys = fila.get("keys") or []
        if _firma(list(other_keys)) == mia:
            label = SHORTCUTS[otro_sid].label
            msg = "That shortcut is already used by “" + label + "”. Pick another one."
            return False, msg

    # Reasignarse su propia tecla actual (p.ej. confirmar la fila sin
    # cambiar nada) nunca es un conflicto, aunque esa tecla esté en
    # keys._RESERVADAS: "esc" y "shift" son precisamente las teclas de
    # fábrica de "cancel" y "latch", así que sin este corte caerían en
    # validate_custom() y se rechazarían como si fueran ajenas.
    propia = actuales.get(sid)
    if isinstance(propia, dict) and _firma(list(propia.get("keys") or [])) == mia:
        return True, ""

    if len(names) == 1:
        ok, msg = keys.validate_custom(names[0])
        if not ok:
            return False, msg

    if "f5" in {n.lower() for n in names}:
        msg = "Heads up: F5 is the macOS Dictation key, so macOS may react to it too."
        return True, msg
    return True, ""
