"""El idioma por defecto no puede ser el del autor.

Con `stt.language: "es"` fijo en el config que se distribuye, Whisper transcribe
como español lo que diga cualquiera; y con `app.language: "es"` el refinador
traduce al español lo que un inglés acaba de dictar en inglés. Ambas cosas hacen
que la app parezca rota para todo el que no sea español.
"""
import pathlib

import yaml

from dictador import config as config_mod
from dictador import modes

CONFIG = pathlib.Path(__file__).resolve().parents[1] / "config.yaml"


def _shipped():
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def test_el_config_distribuido_no_fuerza_idioma_de_salida():
    """app.language debe venir vacío: la salida conserva el idioma hablado."""
    assert _shipped()["app"]["language"] in (None, "", "auto")


def test_el_config_distribuido_no_fuerza_idioma_de_transcripcion():
    """stt.language: 'auto' = usar el idioma del sistema de cada usuario."""
    assert _shipped()["stt"]["language"] in (None, "auto")


def test_el_diccionario_distribuido_no_lleva_datos_personales():
    """El diccionario sesga la transcripción: no puede llevar nombres del autor."""
    dicc = " ".join(_shipped()["stt"].get("dictionary") or []).lower()
    for termino in ("ucademy", "eduardo", "crovetto"):
        assert termino not in dicc


def test_sin_idioma_el_prompt_no_pide_traducir():
    """El hint de idioma es lo que traduciría la salida; sin idioma no debe estar."""
    prompt = modes.system_prompt("ordenar", None)
    assert "Escribe la salida en" not in prompt


def test_con_idioma_el_prompt_si_lo_pide():
    assert "Escribe la salida en en" in modes.system_prompt("ordenar", "en")


def test_system_language_devuelve_codigo_de_dos_letras_o_none():
    lang = config_mod.system_language()
    assert lang is None or (isinstance(lang, str) and len(lang) == 2 and lang.islower())
