"""_record_token_usage(): el conteo de tokens no puede impedir ni ensuciar
el pegado. A nivel de módulo (mismo motivo que apply_ai_selection, ver
test_apply_ai_selection.py) para poder testearla sin instanciar VoooxlyApp.

Hallazgo 3: ai_settings.load(self._prefs) corría dentro del try/except de
_process y ANTES de output.deliver(). Si lanzaba, el método abortaba al
catch-all de arriba y el texto ya refinado nunca llegaba a pegarse — el peor
desenlace posible para una tarea de solo contar tokens. stats.bump_tokens ya
estaba bien envuelto; lo que faltaba envolver era la llamada nueva.
"""
from __future__ import annotations

from voooxly import ai_settings, app, stats


class _RefinerFake:
    def __init__(self, last_usage):
        self.last_usage = last_usage


def test_sin_uso_no_llama_a_bump_tokens(monkeypatch):
    llamadas = []
    monkeypatch.setattr(stats, "bump_tokens", lambda *a, **k: llamadas.append((a, k)))
    app._record_token_usage(_RefinerFake(None), {})
    assert not llamadas


def test_con_uso_llama_a_bump_tokens_con_el_proveedor_guardado(monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        stats, "bump_tokens", lambda tokens, provider: llamadas.append((tokens, provider))
    )
    prefs = {"ai_provider": "groq", "ai_model": "llama-3.3-70b-versatile"}
    app._record_token_usage(_RefinerFake(321), prefs)
    assert llamadas
    tokens, provider = llamadas[0]
    assert tokens == 321
    assert provider  # el label del proveedor guardado en prefs


def test_ai_settings_load_roto_no_lanza(monkeypatch):
    """Si ai_settings.load() lanzara (prefs.json corrupto, un tipo
    inesperado...) esto NO puede escapar: en _process corre DESPUÉS de
    output.deliver(), y perder el pegado por un fallo al contar tokens es
    justo lo que este hallazgo prohíbe."""
    def load_roto(prefs):
        raise RuntimeError("prefs.json corrupto")

    monkeypatch.setattr(ai_settings, "load", load_roto)
    app._record_token_usage(_RefinerFake(100), {})  # no debe lanzar


def test_bump_tokens_roto_tampoco_escapa(monkeypatch):
    def bump_roto(*a, **k):
        raise RuntimeError("disco lleno")

    monkeypatch.setattr(stats, "bump_tokens", bump_roto)
    app._record_token_usage(_RefinerFake(100), {})  # no debe lanzar
