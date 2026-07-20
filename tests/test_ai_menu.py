"""Etiquetas del submenú AI engine."""

from voooxly import ai_settings, app, providers


def test_sin_eleccion_ninguno_sale_marcado():
    filas = app.ai_menu_labels(None)
    assert all(activo is False for _, activo in filas)


def test_el_elegido_sale_marcado_y_solo_el():
    sel = ai_settings.Selection(providers.get("groq"), "https://api.groq.com/openai/v1", "m")
    filas = app.ai_menu_labels(sel)
    activos = [etq for etq, activo in filas if activo]
    assert len(activos) == 1
    assert "Groq" in activos[0]


def test_estan_todos_los_proveedores():
    filas = app.ai_menu_labels(None)
    assert len(filas) == len(providers.PROVIDERS)


def test_todas_las_entradas_llevan_puntos_suspensivos():
    """Convención de macOS: '…' = el clic abre un diálogo. TODAS lo hacen:
    los de pago piden la key, custom pide URL/modelo, y Ollama abre el
    selector de modelos instalados."""
    for etq, _ in app.ai_menu_labels(None):
        assert etq.endswith("…"), etq
