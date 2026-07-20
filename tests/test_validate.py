"""validate() manda una generación real y traduce el fallo a algo legible."""

import copy
import os

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


def test_falla_si_no_hay_modelo_elegido():
    """Con modelo vacío (p.ej. tras borrar la key de config.yaml) el mensaje
    debe pedir elegir un modelo, nunca hablar de "reach"/"connect" — ese
    texto llevaba al usuario a depurar su red por un modelo sin elegir."""
    ok, msg = refine.validate(seleccion(model=""), None)
    assert ok is False
    assert "model" in msg.lower()
    assert "reach" not in msg.lower()
    assert "connect" not in msg.lower()


def test_falla_si_no_hay_modelo_no_hace_ninguna_peticion(monkeypatch):
    """El guard tiene que cortar ANTES de _probe(): sin modelo no debe salir
    ninguna petición HTTP."""
    llamadas = []
    monkeypatch.setattr(
        refine.requests, "post", lambda *a, **k: llamadas.append(a or k) or None
    )
    ok, _ = refine.validate(seleccion(model=""), None)
    assert ok is False
    assert llamadas == []


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


# --- Hallazgo 4: el probe no puede taparse con el fallback de dictado en vivo ---
#
# _openai() y _claude() caen a Ollama si el backend remoto falla — correcto
# para un dictado real, donde el usuario prefiere texto sin refinar a nada.
# Pero _probe() reutiliza esos mismos métodos: sin modo estricto, un candidato
# openai/claude roto (key inválida, sin red, base_url que no existe) caía al
# Ollama YA CONFIGURADO en la máquina, que respondía bien, y validate() daba
# éxito nombrando un proveedor que en realidad nunca contestó. Ninguno de
# estos tests monkeypatchea _probe: ejercitan _openai/_claude de verdad contra
# un requests.post fake, igual que los de "Hallazgo 1".


def test_probe_openai_que_falla_no_cae_al_ollama_configurado(monkeypatch):
    """Sin el modo estricto, esta prueba fallaría: fake_post respondería "OK"
    en la segunda llamada (el fallback a Ollama) y validate() devolvería
    éxito para un candidato que en realidad devolvió 401."""
    llamadas = []

    def fake_post(url, **kwargs):
        llamadas.append(url)
        if "candidate.example" in url:
            raise Exception("401 unauthorized")
        # Si esto llega a llamarse es porque el fallback a Ollama se coló:
        # responde bien a propósito para demostrar que taparía el fallo.
        return _FakeResp(200, {"message": {"content": "OK"}})

    monkeypatch.setattr(refine.requests, "post", fake_post)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-bad-key")

    sel = ai_settings.Selection(
        provider=providers.get("openai"),
        base_url="https://candidate.example/v1",
        model="gpt-4o-mini",
    )
    ok, msg = refine.validate(sel, "sk-bad-key", timeout=5.0)
    assert ok is False
    # Sólo la llamada al candidato: si el fallback se hubiera colado habría
    # una segunda llamada (al host de Ollama).
    assert llamadas == ["https://candidate.example/v1/chat/completions"]


def test_probe_claude_que_falla_no_cae_al_ollama_configurado(monkeypatch):
    """Misma idea con kind="claude": _claude() usa el SDK de anthropic, no
    requests.post directamente, así que la key inválida se simula ahí. El
    requests.post fake queda para demostrar que el fallback a Ollama (si se
    colara) respondería bien y taparía el fallo."""
    import anthropic

    llamadas = []

    def fake_post(url, **kwargs):
        llamadas.append(url)
        return _FakeResp(200, {"message": {"content": "OK"}})

    monkeypatch.setattr(refine.requests, "post", fake_post)

    class _ClienteQueFalla:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise Exception("401 invalid x-api-key")

    monkeypatch.setattr(anthropic, "Anthropic", lambda: _ClienteQueFalla())

    sel = ai_settings.Selection(
        provider=providers.get("claude"),
        base_url=providers.get("claude").base_url,
        model="claude-sonnet-5",
    )
    ok, msg = refine.validate(sel, "clave-invalida", timeout=5.0)
    assert ok is False
    # Ninguna llamada a requests.post: si el fallback a Ollama se hubiera
    # colado, habría una (y encima respondería "OK", tapando el fallo).
    assert llamadas == []


def test_dictado_en_vivo_sigue_cayendo_a_ollama_si_openai_falla(monkeypatch):
    """El Refiner normal (el que usa app.py para dictar) NO es estricto: si el
    backend remoto falla en mitad de un dictado, el usuario debe seguir
    recibiendo texto (sin refinar) en vez de nada."""
    llamadas = []

    def fake_post(url, **kwargs):
        llamadas.append(url)
        if "api.openai.com" in url:
            raise Exception("network fail")
        return _FakeResp(200, {"message": {"content": "texto refinado por ollama"}})

    monkeypatch.setattr(refine.requests, "post", fake_post)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-key")

    r = refine.Refiner(_FakeCfg({"llm.backend": "openai"}))
    assert r.strict is False
    salida = r._openai("system", "user")
    assert salida == "texto refinado por ollama"
    assert len(llamadas) == 2


# --- Hallazgo 5: _ollama también tenía que respetar el modo estricto ---
#
# _claude y _openai ya relanzaban en modo estricto en vez de tapar el fallo,
# pero _ollama se quedó fuera: su except genérico siempre devolvía `user` (la
# transcripción/prompt de entrada) como si fuera la respuesta del modelo. Para
# el dictado real eso es lo correcto (sin red no hay que perder el texto),
# pero _probe(kind="ollama") llama a _ollama() directamente, y validate() sólo
# comprueba que la salida no esté vacía — un Ollama totalmente inalcanzable
# devolvía el prompt "ping" tal cual y validate() lo leía como éxito.


def test_ollama_inalcanzable_en_modo_probe_no_reporta_exito(monkeypatch):
    """Reproducción exacta del revisor: con requests.post lanzando
    ConnectionError, validate() debe devolver (False, ...), no (True,
    "Connected to Ollama...")."""
    import requests

    def sin_red(*a, **k):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(refine.requests, "post", sin_red)

    sel = ai_settings.Selection(
        provider=providers.get("ollama"),
        base_url="http://broken-host:11434",
        model="llama3.2",
    )
    ok, msg = refine.validate(sel, None)
    assert ok is False


def test_ollama_con_timeout_en_modo_probe_no_reporta_exito(monkeypatch):
    """Mismo hallazgo, con un timeout en vez de una conexión rechazada."""
    import requests

    def se_cuelga(*a, **k):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(refine.requests, "post", se_cuelga)

    sel = ai_settings.Selection(
        provider=providers.get("ollama"),
        base_url="http://broken-host:11434",
        model="llama3.2",
    )
    ok, msg = refine.validate(sel, None)
    assert ok is False


def test_dictado_en_vivo_sigue_devolviendo_transcripcion_si_ollama_falla(monkeypatch):
    """El Refiner normal (el que usa app.py para dictar) NO es estricto: si
    Ollama falla en mitad de un dictado, el usuario debe seguir recibiendo su
    transcripción cruda, exactamente como antes de este fix."""
    import requests

    def sin_red(*a, **k):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(refine.requests, "post", sin_red)

    r = refine.Refiner(_FakeCfg())
    assert r.strict is False
    salida = r._ollama("system", "transcripción cruda del usuario")
    assert salida == "transcripción cruda del usuario"


# --- Hallazgo 6: una key rechazada no puede quedarse en os.environ ---
#
# _probe() llama a export_key(selection, api_key) ANTES de generar, porque
# _openai()/_claude() leen la key del entorno. Si la validación falla, nada
# la quitaba: detect_backend() sólo mira PRESENCIA de la variable, así que una
# key recién rechazada sesgaba la próxima auto-detección hacia el proveedor
# que acababa de fallar.


def _sel_openai(model="gpt-4o-mini"):
    prov = providers.get("openai")
    return ai_settings.Selection(provider=prov, base_url=prov.base_url, model=model)


def test_falla_restaura_ausencia_previa_de_la_env_var(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def sin_red(*a, **k):
        raise refine.requests.ConnectionError("nope")

    monkeypatch.setattr(refine.requests, "post", sin_red)

    ok, _ = refine.validate(_sel_openai(), "sk-new-bad-key")

    assert ok is False
    assert "OPENAI_API_KEY" not in os.environ


def test_falla_restaura_el_valor_previo_de_la_env_var(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-old-working")

    def sin_red(*a, **k):
        raise refine.requests.ConnectionError("nope")

    monkeypatch.setattr(refine.requests, "post", sin_red)

    ok, _ = refine.validate(_sel_openai(), "sk-new-bad-key")

    assert ok is False
    assert os.environ.get("OPENAI_API_KEY") == "sk-old-working"


def test_exito_deja_puesta_la_key_nueva(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    resp = _FakeResp(200, {"choices": [{"message": {"content": "OK"}}]})
    monkeypatch.setattr(refine.requests, "post", lambda *a, **k: resp)

    ok, _ = refine.validate(_sel_openai(), "sk-new-working")

    assert ok is True
    assert os.environ.get("OPENAI_API_KEY") == "sk-new-working"
