"""Señal de degradación: el usuario debe saber cuándo la IA no actuó.

Directiva del dueño (2026-07-20): si no hay clave o el proveedor no funciona,
avisar — y pegar igualmente lo que se pueda. El texto crudo por FALLO activa
last_fallback; el texto crudo DELIBERADO (modo literal, sin backend) no.
"""

import sys

import pytest
import requests

from voooxly import refine


class CfgFake:
    def __init__(self, valores):
        self._v = valores

    def get(self, path, default=None):
        return self._v.get(path, default)


def _cfg_ollama():
    return CfgFake({
        "llm.backend": "ollama",
        "llm.ollama.host": "http://localhost:11434",
        "llm.ollama.model": "llama3.2",
        "llm.ollama.timeout": 5,
    })


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


def test_fallo_de_red_marca_last_fallback_y_devuelve_crudo(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(
        requests.ConnectionError("sin red")))
    r = refine.Refiner(_cfg_ollama())
    out = r.refine("hola que tal", "ordenar", "es")
    assert out == "hola que tal"
    assert r.last_fallback


def test_exito_deja_last_fallback_a_none(monkeypatch):
    class R:
        status_code = 200
        text = "{}"
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": "Hola, ¿qué tal?"}}
    monkeypatch.setattr(requests, "post", lambda *a, **k: R())
    r = refine.Refiner(_cfg_ollama())
    assert r.refine("hola que tal", "ordenar", "es") == "Hola, ¿qué tal?"
    assert r.last_fallback is None


def test_modo_literal_no_marca_fallback():
    r = refine.Refiner(_cfg_ollama())
    assert r.refine("tal cual", "literal", "es") == "tal cual"
    assert r.last_fallback is None


def test_backend_none_no_marca_fallback():
    """Sin IA configurada el texto crudo es lo prometido, no un fallo."""
    r = refine.Refiner(CfgFake({"llm.backend": "none"}))
    assert r.refine("hola", "ordenar", "es") == "hola"
    assert r.last_fallback is None


def test_un_exito_despues_de_un_fallo_limpia_el_flag(monkeypatch):
    """El flag es del ÚLTIMO refine(), no una alarma pegajosa."""
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(
        requests.ConnectionError("sin red")))
    r = refine.Refiner(_cfg_ollama())
    r.refine("uno", "ordenar", "es")
    assert r.last_fallback

    class R:
        status_code = 200
        text = "{}"
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": "Dos."}}
    monkeypatch.setattr(requests, "post", lambda *a, **k: R())
    r.refine("dos", "ordenar", "es")
    assert r.last_fallback is None


def test_preludio_de_claude_roto_cae_a_ollama_y_marca_last_fallback(monkeypatch):
    """El import de `anthropic` y la construcción del cliente viven DENTRO
    del try de _claude. Un install roto (o cualquier fallo antes de llamar
    a la API) tiene que seguir el mismo camino que un fallo de la API:
    fallback a Ollama y last_fallback puesto — nunca una excepción que se
    escape de refine() sin avisar al usuario."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    # sys.modules["anthropic"] = None hace que "import anthropic" lance
    # ImportError, sin necesidad de que el paquete esté instalado o no.
    monkeypatch.setitem(sys.modules, "anthropic", None)
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(
        requests.ConnectionError("sin red")))
    r = refine.Refiner(_cfg_claude())
    out = r.refine("hola que tal", "ordenar", "es")
    assert out == "hola que tal"
    assert r.last_fallback


def test_claude_explicito_sin_env_key_despacha_a_claude_igualmente(monkeypatch):
    """Backend "claude" elegido explícitamente despacha SIEMPRE a _claude,
    aunque ANTHROPIC_API_KEY no esté en el entorno (p.ej. la lectura del
    llavero falló al arrancar). Antes, sin la variable, refine() se saltaba
    la rama de Claude y llamaba a _ollama directamente: refinado en silencio
    por el motor equivocado, o fallos atribuidos a Ollama. El camino
    atribuido a Claude debe correr: _claude falla (import roto), cae a
    _ollama, y el fallo de Ollama deja last_fallback puesto."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "anthropic", None)
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(
        requests.ConnectionError("sin red")))

    llamadas_claude = []
    original = refine.Refiner._claude

    def espia(self, system, user):
        llamadas_claude.append(True)
        return original(self, system, user)

    monkeypatch.setattr(refine.Refiner, "_claude", espia)
    r = refine.Refiner(_cfg_claude())
    out = r.refine("hola que tal", "ordenar", "es")
    assert llamadas_claude, "refine() debe despachar a _claude aunque falte la env key"
    assert out == "hola que tal"
    assert r.last_fallback


def test_preludio_de_claude_roto_en_modo_estricto_relanza(monkeypatch):
    """En modo estricto (usado por _probe/validate) el mismo fallo debe
    propagarse: tapar el hueco con Ollama escondería que ESTE candidato
    (Claude) nunca respondió."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setitem(sys.modules, "anthropic", None)
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(
        requests.ConnectionError("sin red")))
    r = refine.Refiner(_cfg_claude())
    r.strict = True
    with pytest.raises(ImportError):
        r.refine("hola que tal", "ordenar", "es")
