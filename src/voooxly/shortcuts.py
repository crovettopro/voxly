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
    return max(0, min(MAX_DELAY_MS, int(valor)))


def resolve(prefs: dict, cfg) -> dict[str, dict]:
    """Estado efectivo de los cuatro atajos: prefs por encima del YAML.

    Devuelve {sid: {"keys": [...], "delay_ms": int}}, más "style" en dictation.
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
