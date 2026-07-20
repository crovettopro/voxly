"""Cascada de auto-detección (detect_backend): qué cuenta como proveedor.

Un Ollama alcanzable pero sin modelo configurado NO es un proveedor: Ollama.app
autoarranca su servidor, y reclamarlo condenaba cada dictado a un 400 + aviso
"AI didn't answer" para siempre (y tapaba las keys de entorno más abajo en la
cascada). Hasta que el usuario lo conecte desde el menú, el pegado crudo debe
seguir limpio y sin avisos.
"""

import requests

from voooxly import refine


class CfgFake:
    def __init__(self, valores):
        self._v = valores

    def get(self, path, default=None):
        return self._v.get(path, default)


class _RespuestaOK:
    ok = True


def _servidor_ollama_alcanzable(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _RespuestaOK())


def _sin_keys_de_entorno(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_ollama_alcanzable_sin_modelo_configurado_no_es_proveedor(monkeypatch):
    """Servidor arriba + llm.ollama.model vacío + sin keys → "none"."""
    # monkeypatch restaura la caché del módulo al terminar: sin fugas entre tests.
    monkeypatch.setattr(refine, "_detected", None)
    _servidor_ollama_alcanzable(monkeypatch)
    _sin_keys_de_entorno(monkeypatch)
    cfg = CfgFake({"llm.ollama.model": ""})
    assert refine.detect_backend(cfg, force=True) == "none"


def test_ollama_sin_modelo_deja_pasar_la_cascada_hasta_claude(monkeypatch):
    """Servidor arriba + modelo vacío + ANTHROPIC_API_KEY → "claude".

    Antes la cascada se detenía en "ollama" por mera alcanzabilidad y una key
    de entorno perfectamente funcional nunca llegaba a usarse.
    """
    monkeypatch.setattr(refine, "_detected", None)
    _servidor_ollama_alcanzable(monkeypatch)
    _sin_keys_de_entorno(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    cfg = CfgFake({"llm.ollama.model": ""})
    assert refine.detect_backend(cfg, force=True) == "claude"


def test_ollama_con_modelo_configurado_sigue_detectandose(monkeypatch):
    """Servidor arriba + modelo configurado → "ollama", como siempre."""
    monkeypatch.setattr(refine, "_detected", None)
    _servidor_ollama_alcanzable(monkeypatch)
    _sin_keys_de_entorno(monkeypatch)
    cfg = CfgFake({"llm.ollama.model": "llama3.2"})
    assert refine.detect_backend(cfg, force=True) == "ollama"
