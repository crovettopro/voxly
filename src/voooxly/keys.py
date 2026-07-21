"""Catálogo de teclas de dictado y su validación.

Un módulo de datos, sin AppKit, por el mismo motivo que existe ai_settings.py:
instanciar VoooxlyApp construye menús y no se puede hacer en un test. Aquí vive
toda la lógica que se puede verificar; app.py solo cablea el menú.

La validación es la parte importante. Elegir mal la tecla de dictado no es un
detalle de configuración: inutiliza el teclado. Con "a" de tecla de dictado
dejas de poder escribir la letra a en todo el sistema, y para arreglarlo hay
que editar prefs.json a mano — cosa que el usuario que necesita este menú no
sabe hacer.

GUARDA (guard=True): los modificadores IZQUIERDOS se usan constantemente en
combos (⌘C, ⌘V, ⌘S, ⌘Tab). hotkey.py dispara on_start() (modo hold) u
on_toggle() (modo toggle) al caer la tecla, así que sin guarda cada ⌘C
arrancaría o alternaría una grabación EN CUALQUIERA de los dos modos —
needs_guard() no distingue por dictation_mode porque la tecla la necesita
pase lo que pase en Settings → Dictation style. Con guarda, el disparo solo
ocurre si mantienes la tecla SOLA ~300ms (en modo toggle eso cambia el gesto
de un tap a un mantener breve). Las derechas no la llevan: casi nadie hace
combos con ellas, la ruta actual ya está en producción y dársela costaría
300ms de latencia a todo el mundo para arreglar un problema que solo tienen
las izquierdas.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_KEY = "cmd_r"
DEFAULT_MODE = "hold"

# Modo del botón de dictado. El texto es el que se ve en el menú.
MODES: dict[str, str] = {
    "hold": "Hold to talk",
    "toggle": "Press to start / stop",
}

# Prefijos de los modificadores: se usan en combos, así que necesitan guarda.
_MODIFICADORES = ("cmd", "alt", "ctrl")

# Los modificadores con lado que pynput conoce de verdad. Se listan enteros en
# vez de deducirlos con un sufijo "_l"/"_r" porque alt_gr no lo cumple y la
# deducción generaba mensajes de error absurdos ("prueba alt__r").
_MODIFICADORES_CON_LADO = {
    "cmd_l", "cmd_r", "alt_l", "alt_r", "alt_gr", "ctrl_l", "ctrl_r",
}

# Teclas con dueño: no se pueden reasignar a dictado sin dejar la app coja.
_RESERVADAS = {"esc", "shift", "shift_l", "shift_r"}

# alt_gr no está en el catálogo pero pynput la colapsa en el mismo miembro de
# enum que alt_r: en macOS no existe una tecla AltGr física distinta de la
# Option derecha, así que ambas comparten virtual keycode y `Key.alt_gr is
# Key.alt_r` (verificado contra el pynput del proyecto). needs_guard() tiene
# que saberlo: sin este alias trataría alt_gr como "un modificador
# cualquiera" y le pondría guarda, incoherente con que el catálogo ya trata
# las derechas — que es lo que alt_gr ES de verdad — sin guarda.
_ALIAS_MISMA_TECLA = {"alt_gr": "alt_r"}

# Nombres de pynput que aceptamos fuera del catálogo. Ya no hay entrada
# "Custom…" en el menú (la retiramos: ver DICTATION_KEYS), pero validate_custom
# sigue siendo la puerta de prefs.json y de config.yaml > hotkeys.toggle, que
# es por donde entra hoy quien quiera una F.
# Las funciones llegan hasta f20 en pynput.
_FUNCIONES = {f"f{i}" for i in range(1, 21)}


@dataclass(frozen=True)
class DictationKey:
    name: str    # nombre pynput
    label: str   # etiqueta del menú
    guard: bool  # ¿necesita ventana de decisión?


# El orden es el del menú (orden de inserción): las derechas primero porque son
# las recomendadas y las izquierdas después, con el retardo escrito en la propia
# etiqueta.
#
# Solo los seis modificadores de la fila de abajo. Las F estuvieron aquí y se
# retiraron: F13-F15 no existen en ningún teclado de portátil, así que a quien
# abría el menú en un MacBook le sobraban cuatro filas de diez que no podía
# pulsar — y una lista donde casi la mitad no funciona hace dudar del resto.
# Siguen aceptándose por config.yaml > hotkeys.toggle (ver _FUNCIONES) para
# quien tenga un teclado que las traiga y sepa editar el YAML.
DICTATION_KEYS: dict[str, DictationKey] = {
    "cmd_r": DictationKey("cmd_r", "Right ⌘ (Command)", False),
    "alt_r": DictationKey("alt_r", "Right ⌥ (Option)", False),
    "ctrl_r": DictationKey("ctrl_r", "Right ⌃ (Control)", False),
    "cmd_l": DictationKey("cmd_l", "Left ⌘ (Command) — 300 ms delay", True),
    "alt_l": DictationKey("alt_l", "Left ⌥ (Option) — 300 ms delay", True),
    "ctrl_l": DictationKey("ctrl_l", "Left ⌃ (Control) — 300 ms delay", True),
}


def get(name: str) -> DictationKey | None:
    return DICTATION_KEYS.get(name)


def needs_guard(name: str) -> bool:
    """¿Esta tecla necesita ventana de decisión antes de empezar a grabar?

    Las del catálogo lo llevan escrito. Una custom la necesita si es un
    modificador (se usa en combos); una función o una multimedia, no.
    """
    k = get(_ALIAS_MISMA_TECLA.get(name, name))
    if k is not None:
        return k.guard
    return _es_modificador(name)


def _es_modificador(name: str) -> bool:
    return any(name.startswith(p) for p in _MODIFICADORES)


def validate_custom(name: str) -> tuple[bool, str]:
    """¿Sirve `name` como tecla de dictado? Devuelve (ok, mensaje).

    El mensaje de error dice qué está mal Y cómo arreglarlo: quien llega aquí
    es justo el usuario que no sabe qué es un "nombre de tecla de pynput".
    Acepta cualquier tipo, no solo str: esta función queda cableada a la
    entrada del menú, y un valor no-string ahí no es un caso de laboratorio
    sino lo primero que puede llegar de una entrada de texto sin validar.
    """
    if not isinstance(name, str):
        return False, "A key name must be text, not a number or other value."
    name = name.strip().lower()
    if not name:
        return False, "Type a key name, for example f13 or alt_r."
    if name in DICTATION_KEYS:
        return True, ""
    if len(name) == 1:
        return False, (
            f'"{name}" is a single character — using it for dictation would stop '
            f'you typing "{name}" anywhere on your Mac. Try f13 or alt_r.'
        )
    if name in _RESERVADAS:
        dueno = "cancel a dictation" if name.startswith("esc") else "latch a long dictation"
        return False, f'"{name}" is already used to {dueno}. Pick another key.'
    if name in _MODIFICADORES:
        # OJO: no decir que "{name}" a secas casaría con las dos manos — en
        # macOS solo casa con la izquierda (pynput colapsa Key.cmd_l en
        # Key.cmd; ver hotkey._canon). Ese mensaje era falso, y encima el
        # "arreglo" que sugería antes ({name}_l) canonicaliza de vuelta al
        # mismo "{name}" plano. Se pide lado sin afirmar cuál casa hoy.
        return False, (
            f'"{name}" needs a side — use {name}_l for the left key '
            f"or {name}_r for the right key."
        )
    if name in _MODIFICADORES_CON_LADO or name in _FUNCIONES:
        return True, ""
    return False, (
        f'"{name}" isn\'t a key pynput knows, so it would never fire. '
        f"Try f13, f18 or alt_r."
    )


def resolve(prefs: dict, cfg) -> tuple[str, str, bool]:
    """(tecla, modo, guarda) efectivos: prefs del usuario por encima del YAML.

    Mismo patrón que `sounds` en app.py — config.yaml es el valor de fábrica y
    lo que eligió el usuario manda. Ni unos prefs corruptos (una lista, un
    número, una tecla retirada en una versión posterior) ni un YAML corrupto
    (un string suelto donde debía ir una lista, un tipo que ni se puede
    indexar) pueden dejar la app sin hotkey: ~/.voooxly/config.yaml es
    manuscrito por quien lo tenga y "toggle: cmd_r" en vez de
    "toggle: [cmd_r]" es un error de tecleo, no un caso exótico. Las dos
    fuentes pasan por la misma puerta — validate_custom — y las dos caen al
    DEFAULT_KEY si no la pasan.
    """
    tecla = DEFAULT_KEY
    del_yaml = cfg.get("hotkeys.toggle", [DEFAULT_KEY]) or [DEFAULT_KEY]
    if isinstance(del_yaml, list) and del_yaml:
        candidata_yaml = del_yaml[0]
        if isinstance(candidata_yaml, str) and validate_custom(candidata_yaml)[0]:
            tecla = candidata_yaml

    guardada = prefs.get("dictation_key")
    if isinstance(guardada, str) and validate_custom(guardada)[0]:
        tecla = guardada

    modo = cfg.get("hotkeys.toggle_mode", DEFAULT_MODE)
    modo_guardado = prefs.get("dictation_mode")
    if isinstance(modo_guardado, str) and modo_guardado in MODES:
        modo = modo_guardado
    if modo not in MODES:
        modo = DEFAULT_MODE

    return tecla, modo, needs_guard(tecla)
