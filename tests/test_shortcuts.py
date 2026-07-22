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


def test_un_delay_no_finito_no_rompe_todos_los_atajos():
    # json.dump escribe Infinity y NaN en floats no finitos: un valor de prefs.json
    # con delay_ms: Infinity o delay_ms: NaN es posible sin que nadie edite a mano.
    # float('inf') e float('nan') son instancias de float, así que pasan las guardas
    # de tipo actuales y causan OverflowError / ValueError en int(valor).
    # Un delay no finito no debe dejar la app sin atajos: es un error de la pila de
    # serialización, no un fallo del usuario.
    for delay_invalido in (float('inf'), float('nan')):
        r = shortcuts.resolve(
            {"shortcuts": {"dictation": {"keys": ["cmd_l"], "delay_ms": delay_invalido}}},
            _Cfg()
        )
        # El delay debe caer al default sin lanzar OverflowError / ValueError
        # cmd_l necesita guarda, así que el default es DEFAULT_DELAY_MS, no 0
        assert r["dictation"]["delay_ms"] == shortcuts.DEFAULT_DELAY_MS, f"delay_invalido={delay_invalido}"
        # Crítico: todos los cuatro atajos deben resolverse, no solo "dictation"
        assert "cycle_mode" in r
        assert "latch" in r
        assert "cancel" in r
        assert r["cycle_mode"]["keys"] == ["ctrl", "shift", "m"], f"delay_invalido={delay_invalido}"
        assert r["latch"]["keys"] == ["shift"], f"delay_invalido={delay_invalido}"
        assert r["cancel"]["keys"] == ["esc"], f"delay_invalido={delay_invalido}"


def test_side_hint_de_una_tecla_de_lado_unico():
    # dictation y cancel casan por igualdad exacta (hotkey.py:397 y :432): un
    # nombre con lado siempre casa solo ese lado, sin ambigüedad posible.
    assert shortcuts.side_hint("dictation", ["cmd_r"]) == "right"
    assert shortcuts.side_hint("dictation", ["cmd_l"]) == "left"
    assert shortcuts.side_hint("cancel", ["esc"]) == ""


def test_side_hint_de_un_combo_no_tiene_lado():
    # Un combo de tres teclas no es "de un lado": ctrl+shift+m no distingue
    # el ctrl izquierdo del derecho, y afirmar uno de los dos sería mentir
    # sobre lo que el binding realmente exige.
    assert shortcuts.side_hint("cycle_mode", ["ctrl", "shift", "m"]) == ""


def test_side_hint_del_latch_de_fabrica_casa_las_dos_manos():
    # hotkey.py:421 casa "shift" Y "shift_r" (matcheo de PREFIJO, documentado
    # en hotkey.py:158: "shift también casa shift_r"). Con el shift de fábrica,
    # decir "left" sería falso: el shift derecho también fija la grabación.
    assert shortcuts.side_hint("latch", ["shift"]) == "either side"


def test_side_hint_de_latch_reasignado_a_una_tecla_con_lado_ya_no_ensancha():
    # Si latch pasa a cmd_r, el prefijo que ensancharía sería "cmd_r_" — nada
    # empieza así, así que solo la Cmd derecha casa en runtime. El
    # ensanchamiento de hotkey.py es exclusivo de los modificadores SIN lado
    # ("shift", "cmd", "alt", "ctrl"), no una propiedad general del atajo
    # latch: rebindear a una tecla con lado propio vuelve a ser side-specific.
    assert shortcuts.side_hint("latch", ["cmd_r"]) == "right"


def test_matched_keys_del_latch_de_fabrica_incluye_las_dos_manos():
    # El hecho crudo detrás de side_hint("latch", ["shift"]) == "either side":
    # hotkey.py:421 casa "shift" (igualdad) Y "shift_r" (prefijo). Las dos
    # deben aparecer en el conjunto, canonicalizadas.
    assert shortcuts.matched_keys("latch", ["shift"]) == {"shift", "shift_r"}


def test_matched_keys_de_latch_con_lado_propio_no_ensancha():
    assert shortcuts.matched_keys("latch", ["cmd_r"]) == {"cmd_r"}


def test_matched_keys_fuera_de_latch_nunca_ensancha():
    # dictation/cancel/cycle_mode casan por igualdad exacta (hotkey.py:397 y
    # :432): un modificador sin lado ahí es SOLO la izquierda, nunca las dos.
    assert shortcuts.matched_keys("dictation", ["cmd"]) == {"cmd"}
    assert shortcuts.matched_keys("cancel", ["esc"]) == {"esc"}


def test_matched_keys_de_un_combo_canonicaliza_cada_tecla_sin_ensanchar():
    # ctrl+shift+m: hotkey.py:439 compara el conjunto pulsado por IGUALDAD
    # con el combo entero, así que cada tecla casa solo su propio lado.
    assert shortcuts.matched_keys("cycle_mode", ["ctrl", "shift", "m"]) == {"ctrl", "shift", "m"}


def test_matched_keys_canonicaliza_cmd_l_a_cmd():
    # cmd_l y cmd son la misma tecla física (pynput colapsa la izquierda).
    assert shortcuts.matched_keys("dictation", ["cmd_l"]) == {"cmd"}


def test_los_atajos_llevan_las_claves_exactas_esperadas():
    # Tareas posteriores leen esta forma: dictation lleva delay_ms y style, los
    # otros tres solo "keys". Esta prueba blinda esa forma contractual.
    r = shortcuts.resolve({}, _Cfg())
    assert set(r["dictation"].keys()) == {"keys", "delay_ms", "style"}
    assert set(r["cycle_mode"].keys()) == {"keys"}
    assert set(r["latch"].keys()) == {"keys"}
    assert set(r["cancel"].keys()) == {"keys"}
