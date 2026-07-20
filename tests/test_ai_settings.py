"""Elección de proveedor persistida en prefs.json."""

from voooxly import ai_settings


def test_sin_eleccion_previa_devuelve_none():
    assert ai_settings.load({}) is None


def test_guardar_y_recuperar_la_eleccion():
    prefs = ai_settings.save({}, "groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile")
    sel = ai_settings.load(prefs)
    assert sel.provider.key == "groq"
    assert sel.model == "llama-3.3-70b-versatile"
    assert sel.base_url == "https://api.groq.com/openai/v1"


def test_guardar_no_pisa_otras_preferencias():
    prefs = ai_settings.save({"sounds": False}, "openai", "https://api.openai.com/v1", "gpt-4o-mini")
    assert prefs["sounds"] is False


def test_guardar_no_modifica_el_dict_del_llamador():
    """save() no debe mutar el dict original del llamador."""
    original = {"sounds": False, "other": "value"}
    ai_settings.save(original, "openai", "https://api.openai.com/v1", "gpt-4o-mini")
    # El dict original no debe contener las claves de proveedor
    assert ai_settings.CLAVE_PROVEEDOR not in original
    assert ai_settings.CLAVE_BASE_URL not in original
    assert ai_settings.CLAVE_MODELO not in original
    # Pero conserva sus propias claves
    assert original["sounds"] is False
    assert original["other"] == "value"


def test_al_guardar_sin_url_ni_modelo_se_usan_los_del_preset():
    prefs = ai_settings.save({}, "openai", "", "")
    sel = ai_settings.load(prefs)
    assert sel.base_url == "https://api.openai.com/v1"
    assert sel.model == "gpt-4o-mini"


def test_proveedor_guardado_que_ya_no_existe_se_ignora():
    """Si una versión futura retira un preset, la app no puede petar al arrancar."""
    assert ai_settings.load({"ai_provider": "proveedor-retirado"}) is None


def test_guardar_proveedor_desconocido_lanza():
    import pytest

    with pytest.raises(ValueError):
        ai_settings.save({}, "no-existe", "", "")


def test_cargar_con_proveedor_no_string_devuelve_none():
    """Si prefs.json se corrompe y ai_provider es una lista u otro tipo, load() retorna None.

    Esto previene que la app muera al arrancar por un archivo corrupto.
    """
    # Prefs con ai_provider como lista (corrupción simulada)
    prefs = {"ai_provider": ["ollama"], "other": "data"}
    assert ai_settings.load(prefs) is None
    # Pero no daña el dict
    assert prefs == {"ai_provider": ["ollama"], "other": "data"}


def test_cargar_con_proveedor_dict_devuelve_none():
    """Otro tipo no-string corrupto también es tolerado."""
    prefs = {"ai_provider": {"nested": "dict"}}
    assert ai_settings.load(prefs) is None


def test_save_solo_persiste_la_whitelist_y_nunca_material_de_key():
    """Candado del criterio del spec: ninguna API key en ningún fichero bajo
    ~/.voooxly/. save() es la única puerta de la elección de proveedor hacia
    prefs.json: su salida debe ser EXACTAMENTE la whitelist conocida (las tres
    CLAVE_*) más lo que ya viniera en el dict de entrada, y ningún valor puede
    ser material de key — de hecho la firma de save() ni siquiera puede
    recibirlo, que es lo que este test documenta con el centinela.
    """
    SECRETO_CENTINELA = "sk-CENTINELA-que-jamas-se-pasa-a-save"
    prefs = ai_settings.save({}, "groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile")
    assert set(prefs) == {
        ai_settings.CLAVE_PROVEEDOR,
        ai_settings.CLAVE_BASE_URL,
        ai_settings.CLAVE_MODELO,
    }
    assert all(v != SECRETO_CENTINELA for v in prefs.values())
