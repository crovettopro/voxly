"""Elección de proveedor persistida en prefs.json."""

from voooxly import ai_settings


def test_sin_eleccion_previa_devuelve_none():
    assert ai_settings.load({}) is None


def test_guardar_y_recuperar_la_eleccion():
    prefs = ai_settings.save({}, "groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile")
    sel = ai_settings.load(prefs)
    assert sel.provider.key == "groq"
    assert sel.model == "llama-3.3-70b-versatile"


def test_guardar_no_pisa_otras_preferencias():
    prefs = ai_settings.save({"sounds": False}, "openai", "https://api.openai.com/v1", "gpt-4o-mini")
    assert prefs["sounds"] is False


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
