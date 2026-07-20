"""validate() manda una generación real y traduce el fallo a algo legible."""

import copy

import pytest

from voooxly import ai_settings, providers, refine


def seleccion(key="ollama", model="llama3.2"):
    return ai_settings.Selection(
        provider=providers.get(key),
        base_url=providers.get(key).base_url,
        model=model,
    )


class _FakeCfg:
    """Config mínima para instanciar un Refiner sin tocar la real."""

    def __init__(self, valores=None):
        self._valores = valores or {}

    def get(self, path, default=None):
        return self._valores.get(path, default)


class _FakeResp:
    """Respuesta HTTP fake para monkeypatchear requests.post."""

    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")


def test_ok_cuando_el_modelo_responde(monkeypatch):
    monkeypatch.setattr(refine, "_probe", lambda *a, **k: "OK")
    ok, msg = refine.validate(seleccion(), None)
    assert ok is True
    assert "llama3.2" in msg


def test_falla_nombrando_el_modelo_que_no_existe(monkeypatch):
    """El caso glm-5.2:cloud: el servidor responde, el modelo no está."""
    def explota(*a, **k):
        raise refine.ModelNotAvailable("model 'glm-5.2:cloud' not found")

    monkeypatch.setattr(refine, "_probe", explota)
    ok, msg = refine.validate(seleccion(model="glm-5.2:cloud"), None)
    assert ok is False
    assert "glm-5.2:cloud" in msg


def test_falla_si_el_proveedor_pide_key_y_no_hay():
    ok, msg = refine.validate(seleccion("groq", "llama-3.3-70b-versatile"), None)
    assert ok is False
    assert "key" in msg.lower()


def test_falla_legible_si_no_hay_red(monkeypatch):
    import requests

    def sin_red(*a, **k):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(refine, "_probe", sin_red)
    ok, msg = refine.validate(seleccion(), None)
    assert ok is False
    assert msg and "Traceback" not in msg


def test_una_respuesta_vacia_cuenta_como_fallo(monkeypatch):
    monkeypatch.setattr(refine, "_probe", lambda *a, **k: "")
    ok, _ = refine.validate(seleccion(), None)
    assert ok is False


# --- Hallazgo 1: el texto GENERADO no puede disparar ModelNotAvailable ---
# Estos tests NO monkeypatchean _probe: ejercitan _ollama de verdad contra un
# requests.post fake, que es justo lo que los 4 tests de arriba no cubrían.


def test_200_con_no_encontrado_en_el_texto_generado_no_debe_fallar(monkeypatch):
    """Reproduce el hallazgo 1: un 200 cuyo contenido dice "not found" (porque
    el usuario dictó esa frase) tiene que devolverse tal cual, nunca lanzar
    ModelNotAvailable."""
    contenido = "The file was not found in the folder, so I created it."
    resp = _FakeResp(200, {"message": {"content": contenido}})
    monkeypatch.setattr(refine.requests, "post", lambda *a, **k: resp)

    r = refine.Refiner(_FakeCfg())
    salida = r._ollama("system", "user")
    assert salida == contenido


def test_error_real_de_modelo_ausente_lanza_ModelNotAvailable(monkeypatch):
    """Un error real (status >= 400) con "not found" en el campo JSON de error
    sí tiene que distinguirse como ModelNotAvailable."""
    resp = _FakeResp(404, {"error": "model 'glm-5.2:cloud' not found, try pulling it first"})
    monkeypatch.setattr(refine.requests, "post", lambda *a, **k: resp)

    r = refine.Refiner(_FakeCfg({"llm.ollama.model": "glm-5.2:cloud"}))
    with pytest.raises(refine.ModelNotAvailable):
        r._ollama("system", "user")


# --- Hallazgos 2 y 3: _probe no puede tocar el singleton de config ---


def test_probe_no_modifica_el_singleton_de_config_tras_exito(monkeypatch):
    from voooxly.config import get_config

    cfg = get_config()
    antes = copy.deepcopy(cfg.raw)

    resp = _FakeResp(200, {"message": {"content": "OK"}})
    monkeypatch.setattr(refine.requests, "post", lambda *a, **k: resp)

    ok, _ = refine.validate(seleccion(), None)
    assert ok is True
    assert cfg.raw == antes


def test_probe_no_modifica_el_singleton_de_config_tras_fallo(monkeypatch):
    from voooxly.config import get_config

    cfg = get_config()
    antes = copy.deepcopy(cfg.raw)

    resp = _FakeResp(404, {"error": "model 'llama3.2' not found"})
    monkeypatch.setattr(refine.requests, "post", lambda *a, **k: resp)

    ok, msg = refine.validate(seleccion(), None)
    assert ok is False
    assert cfg.raw == antes


# --- Hallazgo 3: cada "kind" prueba su propia ruta de host/base_url ---


def test_probe_ollama_apunta_al_host_del_candidato_no_al_de_config(monkeypatch):
    llamadas = []
    resp = _FakeResp(200, {"message": {"content": "OK"}})

    def fake_post(url, **kwargs):
        llamadas.append(url)
        return resp

    monkeypatch.setattr(refine.requests, "post", fake_post)

    sel = ai_settings.Selection(
        provider=providers.get("ollama"),
        base_url="http://candidate-host:9999",
        model="llama3.2",
    )
    refine._probe(sel, None, 5.0)
    assert llamadas and llamadas[0].startswith("http://candidate-host:9999")


def test_probe_openai_apunta_al_base_url_del_candidato(monkeypatch):
    llamadas = []
    resp = _FakeResp(200, {"choices": [{"message": {"content": "OK"}}]})

    def fake_post(url, **kwargs):
        llamadas.append(url)
        return resp

    monkeypatch.setattr(refine.requests, "post", fake_post)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    sel = ai_settings.Selection(
        provider=providers.get("openai"),
        base_url="https://candidate.example/v1",
        model="gpt-4o-mini",
    )
    refine._probe(sel, None, 5.0)
    assert llamadas and llamadas[0].startswith("https://candidate.example/v1")
