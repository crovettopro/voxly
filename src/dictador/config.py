"""Carga de configuración: config.yaml + overrides de entorno (.env)."""
from __future__ import annotations

import os
import pathlib
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config.yaml"


def _try_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
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
    p = pathlib.Path(path) if path else DEFAULT_CONFIG
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    return Config(data)


# Singleton perezoso
_cfg: Config | None = None


def get_config() -> Config:
    global _cfg
    if _cfg is None:
        _cfg = load_config()
    return _cfg