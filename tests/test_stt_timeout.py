"""El timeout de /inference tiene que escalar con el audio, no ser fijo.

30s bastaba cuando el tope de grabación era 60s (nunca se vio un timeout en
producción con esa combinación), pero con dictados de hasta 5 min (ver
audio.max_duration) transcribir puede tardar más que eso: el POST expira, el
`except Exception` de transcribe() lo traga y el dictado entero se pierde sin
pegar nada — el mismo bug que arregló subir el tope de grabación, un paso más
adelante en la cadena. Estos tests fijan que el timeout crece con la duración
del audio, con piso de 30s (no regresionar dictados cortos) y techo duro (no
colgar la app para siempre si el server está muerto).
"""
from __future__ import annotations

import threading

import numpy as np
import pytest
import requests

from voooxly import stt
from voooxly.config import load_config


class _FakeResponse:
    ok = True
    status_code = 200
    text = "{}"

    def json(self):
        return {"text": "hola mundo"}


@pytest.fixture(autouse=True)
def _servidor_listo(monkeypatch):
    # Nos saltamos el arranque real del whisper-server: a estos tests solo
    # les interesa qué timeout recibe requests.post.
    ready = threading.Event()
    ready.set()
    monkeypatch.setattr(stt, "_server_ready", ready)
    yield


def _audio_de(segundos: float) -> np.ndarray:
    return np.zeros(int(stt.SR * segundos), dtype=np.int16)


def test_un_dictado_largo_recibe_un_timeout_mayor_a_30s(monkeypatch):
    capturados = []

    def fake_post(url, files=None, data=None, timeout=None):
        capturados.append(timeout)
        return _FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    stt.transcribe(_audio_de(300.0))  # 5 min: el máximo de audio.max_duration
    assert capturados[0] > 30, (
        "300s de audio deben pedir más de los 30s fijos de antes: si no, un "
        "dictado largo real puede expirar y perderse igual que antes de "
        "subir el tope de grabación."
    )


def test_el_timeout_escala_proporcional_a_la_duracion(monkeypatch):
    capturados = []

    def fake_post(url, files=None, data=None, timeout=None):
        capturados.append(timeout)
        return _FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    stt.transcribe(_audio_de(60.0))
    stt.transcribe(_audio_de(300.0))
    corto, largo = capturados
    # 300s es 5x más audio que 60s: el timeout tiene que crecer con ello, no
    # quedarse plano (eso sería el mismo bug con un número distinto).
    assert largo > corto


def test_un_dictado_corto_no_baja_del_piso_de_30s(monkeypatch):
    capturados = []

    def fake_post(url, files=None, data=None, timeout=None):
        capturados.append(timeout)
        return _FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    stt.transcribe(_audio_de(2.0))
    assert capturados[0] >= 30, (
        "un dictado corto contra un server encallado tiene que seguir "
        "fallando rápido, igual que con el timeout fijo de antes."
    )


def test_el_timeout_tiene_un_techo(monkeypatch):
    capturados = []

    def fake_post(url, files=None, data=None, timeout=None):
        capturados.append(timeout)
        return _FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    # Muy por encima de audio.max_duration: un server colgado no puede dejar
    # la app esperando sin fin pase lo que pase con la duración del audio.
    stt.transcribe(_audio_de(3600.0))
    assert capturados[0] <= 200, "el timeout tiene que estar acotado por un techo duro"


def test_el_reintento_tras_connectionerror_usa_el_mismo_timeout_escalado(monkeypatch):
    capturados = []
    intentos = {"n": 0}

    def fake_post(url, files=None, data=None, timeout=None):
        capturados.append(timeout)
        intentos["n"] += 1
        if intentos["n"] == 1:
            raise requests.exceptions.ConnectionError("server no responde")
        return _FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(stt, "start_server", lambda *a, **k: True)
    stt.transcribe(_audio_de(300.0))
    assert len(capturados) == 2, "el reintento tiene que haber ocurrido"
    assert capturados[0] == capturados[1] > 30, (
        "arreglar solo el primer POST y dejar el reintento en 30s fijo deja "
        "vivo el bug en ese camino"
    )


def test_el_yaml_expone_piso_y_techo_del_timeout_de_transcripcion():
    cfg = load_config()
    assert cfg.get("stt.transcribe_timeout_floor", 0) >= 30
    assert cfg.get("stt.transcribe_timeout_ceiling", 0) >= 150
