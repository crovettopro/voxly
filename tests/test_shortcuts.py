"""El registro de atajos: qué existe, cómo se resuelve y qué pasa si está roto.

Un módulo de datos puro, como keys.py y por el mismo motivo: instanciar la
ventana de Shortcuts construye AppKit y eso no corre en un test. Aquí vive
toda la lógica verificable; settings_window.py solo pinta lo que esto decide.

Lo que se prueba con más saña es la resolución con entradas corruptas.
~/.voooxly/prefs.json y config.yaml los edita gente a mano, y ninguna de las
dos fuentes puede dejar la app sin atajos.
"""
from voooxly import shortcuts


class _Cfg:
    """cfg falso con la misma interfaz que config.load(): .get(ruta, default)."""

    def __init__(self, data=None):
        self._data = data or {}

    def get(self, path, default=None):
        return self._data.get(path, default)


def test_existen_los_cuatro_atajos_y_solo_esos():
    assert set(shortcuts.SHORTCUTS) == {"dictation", "cycle_mode", "latch", "cancel"}


def test_solo_dictation_lleva_delay():
    # D4 del diseño: la ventana de desambiguación protege de combos como ⌘C.
    # En esc o en ⌃⇧M no protege de nada y sería latencia gratis.
    assert shortcuts.SHORTCUTS["dictation"].has_delay is True
    for sid in ("cycle_mode", "latch", "cancel"):
        assert shortcuts.SHORTCUTS[sid].has_delay is False, sid


def test_sin_prefs_ni_yaml_salen_los_defaults():
    r = shortcuts.resolve({}, _Cfg())
    assert r["dictation"]["keys"] == ["cmd_r"]
    assert r["dictation"]["style"] == "hold"
    assert r["dictation"]["delay_ms"] == 0      # cmd_r no necesita guarda
    assert r["cycle_mode"]["keys"] == ["ctrl", "shift", "m"]
    assert r["latch"]["keys"] == ["shift"]
    assert r["cancel"]["keys"] == ["esc"]


def test_los_prefs_mandan_sobre_el_yaml():
    cfg = _Cfg({"hotkeys.toggle": ["alt_r"]})
    prefs = {"shortcuts": {"dictation": {"keys": ["ctrl_r"], "style": "hold", "delay_ms": 0}}}
    assert shortcuts.resolve(prefs, cfg)["dictation"]["keys"] == ["ctrl_r"]


def test_unos_prefs_corruptos_no_dejan_la_app_sin_atajo():
    # Una lista donde debía ir un dict, un número donde debía ir una lista:
    # prefs.json lo escribe la app pero lo puede editar cualquiera.
    for basura in ([], 7, "cmd_r", {"dictation": 3}, {"dictation": {"keys": "cmd_r"}}):
        r = shortcuts.resolve({"shortcuts": basura}, _Cfg())
        assert r["dictation"]["keys"] == ["cmd_r"], basura


def test_una_tecla_invalida_en_prefs_cae_al_default():
    # "a" inutilizaría el teclado; validate_custom la rechaza y resolve no la
    # deja pasar aunque esté escrita en el json.
    r = shortcuts.resolve({"shortcuts": {"dictation": {"keys": ["a"]}}}, _Cfg())
    assert r["dictation"]["keys"] == ["cmd_r"]


def test_el_delay_se_recorta_al_rango():
    r = shortcuts.resolve({"shortcuts": {"dictation": {"keys": ["cmd_r"], "delay_ms": 5000}}}, _Cfg())
    assert r["dictation"]["delay_ms"] == shortcuts.MAX_DELAY_MS
    r = shortcuts.resolve({"shortcuts": {"dictation": {"keys": ["cmd_r"], "delay_ms": -3}}}, _Cfg())
    assert r["dictation"]["delay_ms"] == 0


def test_un_delay_no_numerico_cae_al_valor_seguro():
    r = shortcuts.resolve({"shortcuts": {"dictation": {"keys": ["cmd_l"], "delay_ms": "mucho"}}}, _Cfg())
    # cmd_l necesita guarda: sin un delay usable, el valor seguro es el default,
    # NUNCA 0 (con 0 cada ⌘C arrancaría una grabación).
    assert r["dictation"]["delay_ms"] == shortcuts.DEFAULT_DELAY_MS


def test_un_estilo_desconocido_cae_a_hold():
    r = shortcuts.resolve({"shortcuts": {"dictation": {"keys": ["cmd_r"], "style": "bailar"}}}, _Cfg())
    assert r["dictation"]["style"] == "hold"


def test_un_tipo_erroneo_en_hotkeys_toggle_mode_no_rompe_todos_los_atajos():
    # Un error de tecleo en config.yaml como `toggle_mode: [hold]` en lugar de
    # `toggle_mode: hold` puede pasar: es un archivo editado a mano. Ese typo
    # no debe dejar la app sin atajos: la segunda guarda de tipo debe ser tan
    # fuerte como la primera.
    cfg = _Cfg({"hotkeys.toggle_mode": ["hold"]})  # Una lista en lugar de str
    r = shortcuts.resolve({"shortcuts": {}}, cfg)
    # El estilo debe caer al default sin lanzar TypeError
    assert r["dictation"]["style"] == "hold"
    # Crítico: todos los cuatro atajos deben resolverse, no solo "dictation"
    assert "cycle_mode" in r
    assert "latch" in r
    assert "cancel" in r
    assert r["cycle_mode"]["keys"] == ["ctrl", "shift", "m"]
    assert r["latch"]["keys"] == ["shift"]
    assert r["cancel"]["keys"] == ["esc"]
