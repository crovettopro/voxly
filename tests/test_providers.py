"""Catálogo de proveedores: datos puros, sin red."""

from voooxly import providers


def test_los_presets_esperados_existen():
    for key in ("ollama", "claude", "openai", "groq", "openrouter", "custom"):
        assert providers.get(key) is not None, key


def test_ollama_local_no_pide_key():
    assert providers.get("ollama").needs_key is False


def test_los_de_pago_piden_key():
    for key in ("claude", "openai", "groq", "openrouter", "custom"):
        assert providers.get(key).needs_key is True, key


def test_todo_lo_que_no_es_ollama_ni_claude_usa_el_camino_openai():
    for key in ("openai", "groq", "openrouter", "custom"):
        assert providers.get(key).kind == "openai", key
    assert providers.get("ollama").kind == "ollama"
    assert providers.get("claude").kind == "claude"


def test_los_presets_con_url_fija_la_traen_rellena():
    # Proveedores con base_url no vacía: pintar la URL exacta
    providers_with_urls = {
        "ollama": "http://localhost:11434",
        "openai": "https://api.openai.com/v1",
        "groq": "https://api.groq.com/openai/v1",
        "openrouter": "https://openrouter.ai/api/v1",
    }
    for key, expected_url in providers_with_urls.items():
        assert providers.get(key).base_url == expected_url, f"{key} should have base_url={expected_url}"

    # Proveedores con base_url vacía (gestión externa): también lo pinchamos
    for key in ("claude", "custom"):
        assert providers.get(key).base_url == "", f"{key} should have empty base_url"


def test_custom_no_trae_url_porque_la_teclea_el_usuario():
    assert providers.get("custom").base_url == ""


def test_proveedor_desconocido_da_none():
    assert providers.get("no-existe") is None


def test_todas_las_etiquetas_son_distintas():
    labels = [p.label for p in providers.PROVIDERS.values()]
    assert len(labels) == len(set(labels))
