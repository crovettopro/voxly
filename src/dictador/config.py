"""Carga de configuración: config.yaml + overrides de entorno (.env)."""
from __future__ import annotations

import os
import pathlib
import sys
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config.yaml"

# Resolución de config robusta para .app bundle y desarrollo:
# 1. env DICTADOR_CONFIG  2. ~/.dictador/config.yaml (override usuario)
# 3. config junto al binario (pyinstaller _MEIPASS / repo)
def _config_candidates() -> list[pathlib.Path]:
    cands: list[pathlib.Path] = []
    env = os.environ.get("DICTADOR_CONFIG")
    if env:
        cands.append(pathlib.Path(env))
    cands.append(pathlib.Path.home() / ".dictador" / "config.yaml")
    # pyinstaller bundle
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(pathlib.Path(meipass) / "config.yaml")
    cands.append(DEFAULT_CONFIG)
    return cands


def _try_dotenv() -> None:
    for path in (pathlib.Path.home() / ".dictador" / ".env", ROOT / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k and k not in os.environ:
                os.environ[k] = v


def _deep_get(d: dict, path: str, default: Any = None) -> Any:
    cur = d
    for p in path.split("."):
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return default
    return cur


# Map env overrides -> config keys
_ENV_OVERRIDES = {
    "DICTADOR_LLM_BACKEND": "llm.backend",
    "DICTADOR_LLM_OLLAMA_MODEL": "llm.ollama.model",
    "DICTADOR_LLM_OLLAMA_HOST": "llm.ollama.host",
    "DICTADOR_LLM_CLAUDE_MODEL": "llm.claude.model",
    "DICTADOR_STT_MODEL": "stt.model",
    "DICTADOR_STT_LANGUAGE": "stt.language",
    "DICTADOR_APP_MODE": "app.default_mode",
    "DICTADOR_APP_LANGUAGE": "app.language",
    "DICTADOR_APP_OVERLAY": "app.show_overlay",
    "DICTADOR_AUDIO_SILENCE": "audio.silence_to_stop",
    "DICTADOR_OUTPUT_AUTOPASTE": "output.auto_paste",
}


class Config:
    def __init__(self, data: dict):
        self._d = data
        for env_key, cfg_path in _ENV_OVERRIDES.items():
            val = os.environ.get(env_key)
            if val is None:
                continue
            # intenta coerce bool / float / int
            if val.lower() in ("true", "false"):
                val = val.lower() == "true"
            else:
                try:
                    val = float(val) if "." in val else int(val)
                except (ValueError, TypeError):
                    pass
            self._set_path(cfg_path, val)

    def _set_path(self, path: str, val: Any) -> None:
        parts = path.split(".")
        cur = self._d
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = val

    def get(self, path: str, default: Any = None) -> Any:
        return _deep_get(self._d, path, default)

    @property
    def raw(self) -> dict:
        return self._d


def load_config(path: pathlib.Path | str | None = None) -> Config:
    _try_dotenv()
    if path:
        p = pathlib.Path(path)
    else:
        p = next((c for c in _config_candidates() if c.exists()), DEFAULT_CONFIG)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    return Config(data)


def system_language() -> str | None:
    """Código ISO de 2 letras del idioma del sistema ("es", "en"…), o None.

    Es el valor por defecto del STT: forzar un idioma ahorra ~1.4s por petición
    frente a la auto-detección, pero fijarlo en el config que se distribuye
    haría que Whisper transcribiera como español lo que dicte un inglés.
    """
    try:
        from Foundation import NSLocale

        langs = NSLocale.preferredLanguages()
        if langs:
            code = str(langs[0]).split("-")[0].strip().lower()
            if len(code) == 2 and code.isalpha():
                return code
    except Exception:
        pass
    return None


def resolve_language(value: Any) -> str | None:
    """Traduce el valor del config a un idioma efectivo.

    "auto" -> idioma del sistema; None -> que Whisper lo detecte solo;
    cualquier otra cosa -> tal cual (el usuario lo ha fijado a mano).
    """
    if isinstance(value, str) and value.strip().lower() == "auto":
        return system_language()
    return value


# Singleton perezoso
_cfg: Config | None = None


def get_config() -> Config:
    global _cfg
    if _cfg is None:
        _cfg = load_config()
    return _cfg