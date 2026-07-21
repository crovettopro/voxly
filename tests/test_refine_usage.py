"""Conteo de tokens: nunca puede alterar qué texto se pega ni de qué motor.

Hallazgos de revisión sobre d83f3bf (contador de tokens para free tier):

- Nº1: last_usage se asigna ANTES de construir el valor de retorno, así que
  puede quedar con el valor de un proveedor cloud aunque el texto pegado
  termine viniendo de Ollama (fallback) — un dictado atribuido al motor
  equivocado en las stats.
- Nº2: los comentarios "getattr no puede lanzar" sobreclaman: getattr sólo
  traga AttributeError. Cualquier otra excepción durante el conteo (un SDK
  que cambie de forma, entrada/salida no numéricos, `usage` no-dict) escapa
  al except de fuera y dispara un fallback a Ollama de una llamada que en
  realidad funcionó — pegando texto de un motor que el usuario no eligió.
"""
from __future__ import annotations

import sys
import types

import requests

from voooxly import refine


class CfgFake:
    def __init__(self, valores):
        self._v = valores

    def get(self, path, default=None):
        return self._v.get(path, default)


def _cfg_claude():
    return CfgFake({
        "llm.backend": "claude",
        "llm.claude.model": "claude-sonnet-5",
        "llm.claude.max_tokens": 1200,
        "llm.claude.timeout": 30,
        # _claude cae a Ollama si falla: necesita también su propia config.
        "llm.ollama.host": "http://localhost:11434",
        "llm.ollama.model": "llama3.2",
        "llm.ollama.timeout": 5,
    })


def _cfg_openai():
    return CfgFake({
        "llm.backend": "openai",
        "llm.openai.base_url": "https://api.groq.com/openai/v1",
        "llm.openai.model": "llama-3.3-70b-versatile",
        "llm.openai.api_key_env": "GROQ_API_KEY",
        "llm.openai.timeout": 30,
        "llm.ollama.host": "http://localhost:11434",
        "llm.ollama.model": "llama3.2",
        "llm.ollama.timeout": 5,
    })


def _instalar_anthropic_falso(monkeypatch, resp):
    """Sustituye el módulo `anthropic` real por uno que siempre devuelve `resp`."""
    class FakeMessages:
        def create(self, **kwargs):
            return resp

    class FakeAnthropic:
        def __init__(self, *a, **k):
            self.messages = FakeMessages()

    modulo = types.ModuleType("anthropic")
    modulo.Anthropic = FakeAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", modulo)


# --- Hallazgo 1: last_usage no puede quedar rancio tras un fallback ---


def test_claude_content_roto_no_deja_last_usage_con_tokens_de_una_llamada_descartada(monkeypatch):
    """Usage válido pero `content` que revienta al iterarlo: el texto final
    viene de Ollama (fallback), así que last_usage NO puede quedar con los
    tokens de Claude — atribuiría a Claude un gasto de una respuesta que
    nunca se usó."""
    class UsageValido:
        input_tokens = 100
        output_tokens = 50

    class ContentQueRevienta:
        def __iter__(self):
            raise RuntimeError("iterar content explota")

    class RespRota:
        usage = UsageValido()
        content = ContentQueRevienta()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _instalar_anthropic_falso(monkeypatch, RespRota())

    class R:
        status_code = 200
        text = "{}"
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": "Texto de Ollama"}}
    monkeypatch.setattr(requests, "post", lambda *a, **k: R())

    r = refine.Refiner(_cfg_claude())
    out = r.refine("hola", "ordenar", "es")

    assert out == "Texto de Ollama"
    assert r.last_usage is None, "los tokens de Claude no pueden sobrevivir a un fallback"


def test_openai_choices_vacio_no_deja_last_usage_con_tokens_de_una_llamada_descartada(monkeypatch):
    """`usage` llega antes que `choices` en el JSON de respuesta: si choices
    está vacío (IndexError) el texto final viene de Ollama, y last_usage no
    puede quedar con los tokens que anunciaba esa respuesta rota."""
    def fake_post(url, **kwargs):
        if "chat/completions" in url:
            class Rota:
                status_code = 200
                def raise_for_status(self): pass
                def json(self): return {"usage": {"total_tokens": 321}, "choices": []}
            return Rota()
        class Rok:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"message": {"content": "Texto de Ollama"}}
        return Rok()

    monkeypatch.setenv("GROQ_API_KEY", "sk-test")
    monkeypatch.setattr(requests, "post", fake_post)

    r = refine.Refiner(_cfg_openai())
    out = r.refine("hola", "ordenar", "es")

    assert out == "Texto de Ollama"
    assert r.last_usage is None


# --- Hallazgo 2: "getattr no puede lanzar" sobreclama ---


def test_claude_usage_que_lanza_no_tumba_una_llamada_exitosa(monkeypatch):
    """`usage.input_tokens` es una property que lanza algo que NO es
    AttributeError: getattr sólo traga AttributeError, así que esto tumbaba
    una llamada a Claude que SÍ respondió bien y la reintentaba contra
    Ollama."""
    class UsageQueExplota:
        @property
        def input_tokens(self):
            raise RuntimeError("el SDK cambió de forma")
        output_tokens = 50

    class Bloque:
        text = "Texto limpio de Claude"

    class RespBuena:
        usage = UsageQueExplota()
        content = [Bloque()]

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _instalar_anthropic_falso(monkeypatch, RespBuena())
    llamadas = []
    def post_espia(*a, **k):
        llamadas.append(1)
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"message": {"content": "Ollama de emergencia"}}
        return R()
    monkeypatch.setattr(requests, "post", post_espia)

    r = refine.Refiner(_cfg_claude())
    out = r.refine("hola", "ordenar", "es")

    assert out == "Texto limpio de Claude"
    assert not llamadas, "no debería haber fallback a Ollama"
    assert r.last_fallback is None


def test_claude_entrada_mas_salida_no_numerico_no_rompe_una_llamada_exitosa(monkeypatch):
    """`entrada + salida` asume ambos numéricos: con deriva de esquema (uno
    llega como texto) un TypeError no puede tirar por la borda una respuesta
    de Claude que sí llegó bien."""
    class UsageRaro:
        input_tokens = "muchos"
        output_tokens = 50

    class Bloque:
        text = "Otra respuesta válida"

    class RespBuena:
        usage = UsageRaro()
        content = [Bloque()]

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _instalar_anthropic_falso(monkeypatch, RespBuena())
    llamadas = []
    def post_espia(*a, **k):
        llamadas.append(1)
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"message": {"content": "Ollama de emergencia"}}
        return R()
    monkeypatch.setattr(requests, "post", post_espia)

    r = refine.Refiner(_cfg_claude())
    out = r.refine("hola", "ordenar", "es")

    assert out == "Otra respuesta válida"
    assert not llamadas, "no debería haber fallback a Ollama"
    assert r.last_fallback is None
    assert r.last_usage is None  # el conteo se perdió, pero el texto no


def test_openai_usage_no_dict_no_rompe_una_llamada_exitosa(monkeypatch):
    """`usage.get("total_tokens")` asume dict: un proveedor que mande un
    valor truthy no-dict (deriva de esquema) no puede perder una respuesta
    de OpenAI que sí contestó bien."""
    llamadas = []
    def fake_post(url, **kwargs):
        if "chat/completions" in url:
            class Rota:
                status_code = 200
                def raise_for_status(self): pass
                def json(self):
                    return {
                        "usage": "pendiente",  # ni dict ni None: .get() explota
                        "choices": [{"message": {"content": "Respuesta válida de OpenAI"}}],
                    }
            return Rota()
        llamadas.append(1)
        class Rok:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"message": {"content": "Ollama de emergencia"}}
        return Rok()

    monkeypatch.setenv("GROQ_API_KEY", "sk-test")
    monkeypatch.setattr(requests, "post", fake_post)

    r = refine.Refiner(_cfg_openai())
    out = r.refine("hola", "ordenar", "es")

    assert out == "Respuesta válida de OpenAI"
    assert not llamadas, "no debería haber fallback a Ollama"
    assert r.last_fallback is None
    assert r.last_usage is None
