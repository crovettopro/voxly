"""Refinamiento LLM: transforma la transcripción cruda en el texto final según el modo.

Backends:
- ollama: endpoint local http://localhost:11434 (modelo local o cloud enrutado)
- claude: Anthropic API (si ANTHROPIC_API_KEY)
- openai: cualquier endpoint OpenAI-compatible

Cada modo (modes.system_prompt) define el system prompt. El modo "literal" se salta
el LLM y devuelve la transcripción tal cual.
"""
from __future__ import annotations

import logging
import os

import requests

from . import modes

log = logging.getLogger("dictador.refine")


class Refiner:
    def __init__(self, cfg):
        self.cfg = cfg
        self.backend = cfg.get("llm.backend", "ollama")

    def refine(self, transcript: str, mode: str, language: str | None) -> str:
        transcript = (transcript or "").strip()
        if not transcript:
            return ""
        sys_prompt = modes.system_prompt(mode, language)
        if not sys_prompt:  # modo literal
            return transcript

        if self.backend == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
            return self._claude(sys_prompt, transcript)
        if self.backend == "openai":
            return self._openai(sys_prompt, transcript)
        # default + fallback
        return self._ollama(sys_prompt, transcript)

    # --- Ollama ---
    def _ollama(self, system: str, user: str) -> str:
        host = self.cfg.get("llm.ollama.host", "http://localhost:11434")
        model = self.cfg.get("llm.ollama.model", "glm-5.2:cloud")
        temp = self.cfg.get("llm.ollama.temperature", 0.3)
        timeout = self.cfg.get("llm.ollama.timeout", 30)
        try:
            r = requests.post(
                f"{host}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "options": {"temperature": temp},
                },
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.json()
            return (data.get("message", {}).get("content", "") or "").strip()
        except Exception as e:
            log.error("Ollama falló (%s). Devuelvo transcripción sin refinar.", e)
            return user

    # --- Claude ---
    def _claude(self, system: str, user: str) -> str:
        import anthropic

        client = anthropic.Anthropic()
        model = self.cfg.get("llm.claude.model", "claude-sonnet-5")
        max_tokens = self.cfg.get("llm.claude.max_tokens", 1200)
        timeout = self.cfg.get("llm.claude.timeout", 30)
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                timeout=timeout,
            )
            return "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        except Exception as e:
            log.error("Claude falló (%s). Fallback Ollama.", e)
            return self._ollama(system, user)

    # --- OpenAI-compatible ---
    def _openai(self, system: str, user: str) -> str:
        base = self.cfg.get("llm.openai.base_url", "https://api.openai.com/v1")
        model = self.cfg.get("llm.openai.model", "gpt-4o-mini")
        env_key = self.cfg.get("llm.openai.api_key_env", "OPENAI_API_KEY")
        key = os.environ.get(env_key, "")
        temp = self.cfg.get("llm.openai.temperature", 0.3)
        timeout = self.cfg.get("llm.openai.timeout", 30)
        if not key:
            log.warning("Sin %s. Fallback Ollama.", env_key)
            return self._ollama(system, user)
        try:
            r = requests.post(
                f"{base.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": temp,
                },
                timeout=timeout,
            )
            r.raise_for_status()
            return (r.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception as e:
            log.error("OpenAI falló (%s). Fallback Ollama.", e)
            return self._ollama(system, user)


def health() -> dict:
    """Comprueba disponibilidad de cada backend (para el menú)."""
    from .config import get_config

    cfg = get_config()
    out = {}
    # ollama
    try:
        r = requests.get(f"{cfg.get('llm.ollama.host','http://localhost:11434')}/api/tags", timeout=3)
        out["ollama"] = r.ok
    except Exception:
        out["ollama"] = False
    out["claude"] = bool(os.environ.get("ANTHROPIC_API_KEY"))
    out["openai"] = bool(os.environ.get(cfg.get("llm.openai.api_key_env", "OPENAI_API_KEY")))
    return out