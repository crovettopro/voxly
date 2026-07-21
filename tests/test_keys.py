"""El catálogo de teclas de dictado y, sobre todo, su validación.

La validación no es cosmética: elegir mal la tecla de dictado inutiliza el
teclado entero. Con 'a' como tecla de dictado dejas de poder escribir la letra
a en todo el sistema; con 'esc' pierdes el cancelar; con 'cmd' a secas capturas
los dos lados. Estos tests fijan cada puerta.
"""
from voooxly import keys


def test_el_default_es_la_tecla_que_ya_venia_de_fabrica():
    # Cambiar el default migraría en silencio a todo el que ya usa la app.
    assert keys.DEFAULT_KEY == "cmd_r"
    assert keys.DEFAULT_MODE == "hold"


def test_las_derechas_no_llevan_guarda_y_las_izquierdas_si():
    # Las derechas arrancan al instante: es la ruta que ya está en producción
    # y no se toca. Las izquierdas la necesitan o cada ⌘C graba.
    assert keys.needs_guard("cmd_r") is False
    assert keys.needs_guard("alt_r") is False
    assert keys.needs_guard("f13") is False
    assert keys.needs_guard("cmd_l") is True
    assert keys.needs_guard("alt_l") is True
    assert keys.needs_guard("ctrl_l") is True


def test_el_menu_ofrece_las_seis_teclas_de_abajo_y_nada_mas():
    # Solo los seis modificadores de la fila de abajo. Las F salieron del menú
    # porque medio catálogo no existía en el teclado de quien lo abría: los
    # portátiles no traen F13-F15 y un menú con cuatro filas muertas hace
    # dudar de las seis que sí sirven.
    assert set(keys.DICTATION_KEYS) == {
        "cmd_r", "alt_r", "ctrl_r",
        "cmd_l", "alt_l", "ctrl_l",
    }


def test_las_efes_siguen_valiendo_por_custom():
    # Retirarlas del menú no las prohíbe: validate_custom sigue siendo la
    # puerta de prefs.json y config.yaml, y por ahí entran sin guarda.
    for f in ("f6", "f13", "f15", "f20"):
        assert keys.validate_custom(f)[0] is True, f
        assert keys.needs_guard(f) is False, f


def test_las_derechas_van_primero_en_el_menu():
    # El orden del dict es el del menú: lo recomendado arriba.
    assert list(keys.DICTATION_KEYS)[:3] == ["cmd_r", "alt_r", "ctrl_r"]


def test_la_etiqueta_de_las_izquierdas_avisa_del_retardo():
    # El retardo es una consecuencia real de elegirlas. Se ve ANTES de elegir,
    # no se descubre después preguntándose por qué va lento.
    assert "300" in keys.DICTATION_KEYS["cmd_l"].label
    assert "300" not in keys.DICTATION_KEYS["cmd_r"].label


def test_una_letra_suelta_se_rechaza():
    ok, msg = keys.validate_custom("a")
    assert ok is False
    assert "a" in msg.lower()


def test_un_digito_suelto_se_rechaza():
    assert keys.validate_custom("7")[0] is False


def test_validate_custom_no_revienta_con_un_entero_verdadero():
    # 7 es truthy: `(7 or "").strip()` explota con AttributeError si no se
    # comprueba el tipo antes de tocarlo. validate_custom es pública y una
    # tarea posterior la cablea directo a la entrada del menú, así que un
    # valor no-string no puede reventarla — tiene que rechazarse como
    # cualquier otra tecla inválida.
    ok, msg = keys.validate_custom(7)
    assert ok is False
    assert isinstance(msg, str) and msg


def test_validate_custom_rechaza_cualquier_tipo_no_string_sin_reventar():
    # Los no-string falsy (0, [], None) ya degradaban sin reventar porque
    # `(name or "")` los convertía en cadena vacía. Este test fija que
    # también los truthy (7.5, True, listas no vacías) se rechazan en vez de
    # levantar una excepción.
    for malo in (0, [], {}, None, 7.5, True, ["a"]):
        ok, msg = keys.validate_custom(malo)
        assert ok is False, f"{malo!r} debería rechazarse, no reventar"


def test_esc_y_shift_se_rechazan_porque_ya_tienen_dueno():
    assert keys.validate_custom("esc")[0] is False
    assert keys.validate_custom("shift")[0] is False
    assert keys.validate_custom("shift_r")[0] is False


def test_un_modificador_sin_lado_se_rechaza():
    for n in ("cmd", "ctrl", "alt"):
        ok, msg = keys.validate_custom(n)
        assert ok is False, f"{n} debería exigir lado"
        assert "_l" in msg or "_r" in msg, "el error tiene que decir cómo arreglarlo"


def test_el_mensaje_de_modificador_sin_lado_no_afirma_algo_falso():
    # En macOS "cmd" a secas SOLO casa con la tecla izquierda (pynput colapsa
    # Key.cmd_l en Key.cmd), nunca con las dos. El mensaje anterior decía que
    # "casaría con las dos" — falso — y encima recomendaba "cmd_l" como
    # arreglo, que hotkey._canon canonicaliza de vuelta a "cmd". El mensaje
    # tiene que orientar sin afirmar un comportamiento que no existe.
    for n in ("cmd", "ctrl", "alt"):
        _, msg = keys.validate_custom(n)
        bajo = msg.lower()
        assert "both" not in bajo, f'el mensaje de "{n}" sigue afirmando que casa con las dos'
        assert f"{n}_l" in msg and f"{n}_r" in msg


def test_un_nombre_que_pynput_no_conoce_se_rechaza():
    # Aceptarlo daría una tecla que no dispara nunca: fallo mudo, lo peor.
    assert keys.validate_custom("tecla_inventada")[0] is False


def test_una_funcion_alta_se_acepta_sin_guarda():
    ok, _ = keys.validate_custom("f18")
    assert ok is True
    assert keys.needs_guard("f18") is False


def test_alt_gr_se_acepta_y_no_lleva_guarda_porque_es_alt_r():
    # alt_gr no está en el menú pero pynput lo colapsa en el mismo miembro
    # de enum que alt_r (Key.alt_gr is Key.alt_r en macOS: no hay una tecla
    # AltGr física distinta de la Option derecha). Tratarla como "un
    # modificador cualquiera" y ponerle guarda sería incoherente con que el
    # catálogo ya trata las derechas — que es lo que alt_gr ES de verdad —
    # sin guarda.
    ok, _ = keys.validate_custom("alt_gr")
    assert ok is True
    assert keys.needs_guard("alt_gr") is False


def test_resolve_usa_prefs_por_encima_del_yaml():
    cfg = {"hotkeys.toggle": ["cmd_r"], "hotkeys.toggle_mode": "hold"}
    prefs = {"dictation_key": "alt_r", "dictation_mode": "toggle"}
    assert keys.resolve(prefs, _FakeCfg(cfg)) == ("alt_r", "toggle", False)


def test_resolve_cae_al_yaml_sin_prefs():
    cfg = {"hotkeys.toggle": ["f13"], "hotkeys.toggle_mode": "hold"}
    assert keys.resolve({}, _FakeCfg(cfg)) == ("f13", "hold", False)


def test_resolve_ignora_unos_prefs_corruptos():
    # prefs.json puede traer una lista, un número o una tecla retirada en una
    # versión posterior. Ninguno de esos casos puede dejar la app sin hotkey.
    cfg = {"hotkeys.toggle": ["cmd_r"], "hotkeys.toggle_mode": "hold"}
    for malo in ([], 7, "tecla_inventada", None):
        assert keys.resolve({"dictation_key": malo}, _FakeCfg(cfg))[0] == "cmd_r"


def test_resolve_ignora_un_modo_invalido():
    cfg = {"hotkeys.toggle": ["cmd_r"], "hotkeys.toggle_mode": "hold"}
    assert keys.resolve({"dictation_mode": "bailando"}, _FakeCfg(cfg))[1] == "hold"


def test_resolve_cae_al_default_si_el_yaml_trae_un_string_suelto():
    # "toggle: cmd_r" en vez de "toggle: [cmd_r]" es un error de YAML fácil de
    # cometer. Sin comprobar la forma antes de indexar, "alt_r"[0] cuela "a"
    # como tecla de dictado y rompe el teclado en silencio.
    cfg = {"hotkeys.toggle": "alt_r", "hotkeys.toggle_mode": "hold"}
    assert keys.resolve({}, _FakeCfg(cfg))[0] == keys.DEFAULT_KEY


def test_resolve_cae_al_default_si_el_yaml_no_es_subscriptable():
    # Un entero (o cualquier tipo sin __getitem__) en hotkeys.toggle no puede
    # tirar la app entera con un TypeError: se ignora y se cae al default.
    cfg = {"hotkeys.toggle": 42, "hotkeys.toggle_mode": "hold"}
    assert keys.resolve({}, _FakeCfg(cfg))[0] == keys.DEFAULT_KEY


def test_resolve_cae_al_default_si_la_lista_del_yaml_esta_vacia():
    cfg = {"hotkeys.toggle": [], "hotkeys.toggle_mode": "hold"}
    assert keys.resolve({}, _FakeCfg(cfg))[0] == keys.DEFAULT_KEY


def test_resolve_cae_al_default_si_la_tecla_del_yaml_no_pasa_validate_custom():
    # La tecla de prefs pasa por validate_custom antes de aceptarse; la del
    # YAML tenía un atajo que se la saltaba. Con una lista bien formada pero
    # con una tecla inválida dentro (una letra suelta), tiene que rechazarse
    # igual que se rechazaría viniendo de prefs.
    cfg = {"hotkeys.toggle": ["a"], "hotkeys.toggle_mode": "hold"}
    assert keys.resolve({}, _FakeCfg(cfg))[0] == keys.DEFAULT_KEY


class _FakeCfg:
    """La config real solo se usa vía .get(path, default)."""

    def __init__(self, data):
        self._data = data

    def get(self, path, default=None):
        return self._data.get(path, default)
