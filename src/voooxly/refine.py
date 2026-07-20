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

log = logging.getLogger("voooxly.refine")

# Resultado cacheado de la auto-detección (backend "auto"). Se refresca con
# detect_backend(force=True) — el menú "AI engine" y el keepalive lo hacen.
_detected: str | None = None


def detect_backend(cfg=None, force: bool = False) -> str:
    """Cascada de auto-detección del motor LLM disponible.

    ollama corriendo → claude (ANTHROPIC_API_KEY) → openai (key) → "none".
    Con "none" Voooxly pega la transcripción cruda: funciona sin IA instalada.
    """
    global _detected
    if _detected is not None and not force:
        return _detected
    if cfg is None:
        from .config import get_config

        cfg = get_config()
    try:
        r = requests.get(
            f"{cfg.get('llm.ollama.host', 'http://localhost:11434')}/api/tags",
            timeout=1.5,
        )
        if r.ok:
            _detected = "ollama"
            return _detected
    except Exception:
        pass
    if os.environ.get("ANTHROPIC_API_KEY"):
        _detected = "claude"
        return _detected
    if os.environ.get(cfg.get("llm.openai.api_key_env", "OPENAI_API_KEY")):
        _detected = "openai"
        return _detected
    _detected = "none"
    log.info("Sin motor LLM detectado: los dictados se pegan sin refinar.")
    return _detected


def list_ollama_models(host: str, timeout: float = 3.0) -> list[str]:
    """Modelos que el Ollama del usuario dice tener. Nunca lanza.

    Se usa para ofrecerle SUS modelos en vez de presuponer cuál tiene. Cualquier
    fallo devuelve lista vacía: quien llama está construyendo un diálogo y una
    excepción aquí rompería el menú.
    """
    try:
        r = requests.get(f"{host.rstrip('/')}/api/tags", timeout=timeout)
        if not r.ok:
            return []
        modelos = (r.json() or {}).get("models") or []
        if not isinstance(modelos, list):
            return []
        return [n for m in modelos if isinstance(m, dict) and (n := m.get("name"))]
    except Exception:
        log.debug("No pude listar modelos de Ollama en %s", host, exc_info=True)
        return []


class Refiner:
    def __init__(self, cfg):
        self.cfg = cfg
        self.backend = cfg.get("llm.backend", "auto")
        # Modo estricto: sólo lo activa _probe (ver abajo). Con strict=False
        # (siempre en dictado real, vía app.py), _openai/_claude conservan su
        # fallback a Ollama si el backend remoto falla — así el usuario nunca
        # se queda sin texto en mitad de un dictado. En modo estricto ese
        # fallback se desactiva y el error real se relanza, porque _probe
        # necesita saber si EL CANDIDATO responde, no si Ollama responde en
        # su lugar (si no, validate() podía devolver éxito para un proveedor
        # que nunca contestó — el propio Ollama ya configurado tapaba el fallo).
        self.strict = False

    def refine(self, transcript: str, mode: str, language: str | None) -> str:
        transcript = (transcript or "").strip()
        if not transcript:
            return ""
        sys_prompt = modes.system_prompt(mode, language)
        if not sys_prompt:  # modo literal
            return transcript
        # Reglas personales del usuario (llm.custom_rules): se añaden AL FINAL
        # para que puedan matizar cualquier modo ("nunca uses punto y coma",
        # "mi nombre se escribe Eduardo"...). Vacío por defecto.
        custom = str(self.cfg.get("llm.custom_rules", "") or "").strip()
        if custom:
            sys_prompt += "\n\nPersonal rules from the user — always follow them:\n" + custom

        backend = self.backend
        if backend == "auto":
            backend = detect_backend(self.cfg)
        if backend == "none":
            return transcript
        if backend == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
            return self._claude(sys_prompt, transcript)
        if backend == "openai":
            return self._openai(sys_prompt, transcript)
        # default + fallback
        return self._ollama(sys_prompt, transcript)

    # --- Ollama ---
    def _ollama(self, system: str, user: str) -> str:
        host = self.cfg.get("llm.ollama.host", "http://localhost:11434")
        model = self.cfg.get("llm.ollama.model", "")
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
                    # los modelos razonadores (GLM, qwen, deepseek) queman 200-4700
                    # tokens "pensando" antes de responder: 1.6-40s de latencia extra
                    # que no aporta nada para limpiar un dictado
                    "think": False,
                    "options": {"temperature": temp},
                },
                timeout=timeout,
            )
            if r.status_code >= 400:
                # OJO: sólo aquí, con una respuesta de error real. Antes se
                # miraba r.text (el cuerpo crudo) SIN comprobar el status, así
                # que un 200 cuyo texto generado contenía "not found" (p.ej.
                # "The file was not found...") disparaba ModelNotAvailable y
                # el dictado se perdía. Un 2xx nunca puede llegar aquí.
                error_detail = ""
                try:
                    body = r.json()
                    if isinstance(body, dict):
                        error_detail = str(body.get("error", ""))
                except ValueError:
                    pass  # cuerpo de error no-JSON: cae al raise_for_status genérico
                if "not found" in error_detail.lower():
                    raise ModelNotAvailable(f"model '{model}' not found on the Ollama host")
                r.raise_for_status()
            data = r.json()
            return (data.get("message", {}).get("content", "") or "").strip()
        except ModelNotAvailable:
            # Este caso tiene que llegar hasta validate(): es justo lo que distingue
            # "servidor arriba, modelo ausente" de cualquier otro fallo. Si cayera en
            # el except de abajo, quedaría indistinguible y validate() nunca lo vería
            # (el bug de glm-5.2:cloud que originó esta tarea).
            raise
        except Exception as e:
            if self.strict:
                # Mismo motivo que en _claude/_openai: en modo probe, devolver
                # la transcripción tal cual como si fuera la respuesta del
                # modelo es indistinguible de un éxito real para validate()
                # (sólo mira si la salida no está vacía). Sin esto, un Ollama
                # completamente inalcanzable reportaba "Connected" — el mismo
                # bug de falso-positivo que el flag strict existe para evitar.
                raise
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
            if self.strict:
                raise
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
            if self.strict:
                # Mismo motivo que en el except de abajo: en modo probe, "no hay
                # key" es un fallo del candidato, no una señal para tapar el
                # hueco con Ollama.
                raise RuntimeError(f"missing {env_key}")
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
            if self.strict:
                raise
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


def health_summary() -> str:
    """Texto de 'Backend status…' listo para mostrar."""
    h = health()
    if not h:
        return "No AI backend configured."
    return " · ".join(f"{k}: {'✓' if v else '✗'}" for k, v in h.items())


class ModelNotAvailable(Exception):
    """El servidor responde, pero el modelo pedido no está."""


def export_key(selection, api_key: str | None) -> None:
    """Pone la key donde los backends la buscan: os.environ.

    _openai() y _claude() leen la key del entorno (os.environ.get(env_key)), que
    es como funcionaba cuando venía de ~/.voooxly/.env. Con la key en el llavero
    hay que puentearla aquí, o el backend nunca la ve y el flujo entero queda
    bonito sin funcionar.
    """
    if not api_key:
        return
    if selection.provider.kind == "claude":
        os.environ["ANTHROPIC_API_KEY"] = api_key
    else:
        from .config import get_config

        env_key = get_config().get("llm.openai.api_key_env", "OPENAI_API_KEY")
        os.environ[env_key] = api_key


class _CandidateConfig:
    """Vista de solo lectura: config real + los valores del candidato a probar.

    Refiner sólo lee config vía self.cfg.get(path, default), así que basta con
    interceptar aquí las claves que el candidato cambia y delegar el resto al
    Config real. Nada se escribe nunca en el singleton — una validación
    fallida, cancelada o exitosa no puede dejar rastro en la app en marcha.
    """

    def __init__(self, base_cfg, overrides: dict):
        self._base = base_cfg
        self._overrides = overrides

    def get(self, path: str, default=None):
        if path in self._overrides:
            return self._overrides[path]
        return self._base.get(path, default)


def _probe(selection, api_key: str | None, timeout: float) -> str:
    """Una generación mínima por la MISMA ruta que usa un dictado.

    No toca la config real: el Refiner desechable recibe una _CandidateConfig
    que superpone sólo las claves de ESTE candidato sobre la config real.
    Además, cada "kind" tiene su propia ruta de host/base_url: los presets
    openai/groq/openrouter/custom comparten kind="openai" y por tanto
    llm.openai.*, mientras que ollama tiene su propio llm.ollama.host. Escribir
    siempre en llm.openai.base_url (como antes) hacía que un probe de Ollama
    ignorara el host del candidato y probara el que ya hubiera en config, y que
    validar CUALQUIER preset openai-compatible pisara la config de los otros
    tres.
    """
    export_key(selection, api_key)
    from .config import get_config

    kind = selection.provider.kind
    overrides = {
        f"llm.{kind}.model": selection.model,
        # El usuario está mirando un diálogo modal mientras esto corre: el
        # timeout pedido tiene que llegar de verdad al backend. Los tres
        # backends leen su timeout de config (no como parámetro).
        f"llm.{kind}.timeout": timeout,
    }
    if kind == "ollama":
        overrides["llm.ollama.host"] = selection.base_url
    else:
        overrides["llm.openai.base_url"] = selection.base_url

    r = Refiner.__new__(Refiner)
    r.cfg = _CandidateConfig(get_config(), overrides)
    r.backend = kind
    # Sin esto, un candidato openai/claude roto cae al fallback de Ollama de
    # _openai()/_claude() y, si el Ollama YA CONFIGURADO en la máquina del
    # usuario responde bien (lo normal), validate() da éxito nombrando un
    # proveedor que en realidad nunca contestó.
    r.strict = True
    if kind == "ollama":
        return r._ollama("Reply with the single word OK.", "ping")
    if kind == "claude":
        return r._claude("Reply with the single word OK.", "ping")
    return r._openai("Reply with the single word OK.", "ping")


def _env_key_for(selection) -> str | None:
    """Variable de entorno que _probe (vía export_key) toca para este kind.

    None para ollama: no hay key de por medio, nada que restaurar.
    """
    kind = selection.provider.kind
    if kind == "claude":
        return "ANTHROPIC_API_KEY"
    if kind == "ollama":
        return None
    from .config import get_config

    return get_config().get("llm.openai.api_key_env", "OPENAI_API_KEY")


def validate(selection, api_key: str | None, timeout: float = 12.0) -> tuple[bool, str]:
    """Comprueba de verdad que el proveedor refina. Devuelve (ok, mensaje)."""
    if selection.provider.needs_key and not api_key:
        return False, f"{selection.provider.label} needs an API key."
    if not selection.model:
        return False, f"Pick a model for {selection.provider.label}."
    # _probe() exporta la key candidata a os.environ ANTES de generar (los
    # backends la leen de ahí). Si la validación falla, esa key rechazada se
    # queda en el entorno y sesga la próxima detect_backend() (su cascada solo
    # mira PRESENCIA de la variable, no si la key funciona). Snapshot + restore
    # deja el entorno como estaba en cualquier fallo; en éxito la dejamos
    # puesta, porque acaba de demostrar que funciona.
    env_key = _env_key_for(selection)
    prev = os.environ.get(env_key) if env_key else None
    had_prev = env_key is not None and env_key in os.environ

    def _restore_env():
        if not env_key:
            return
        if had_prev:
            os.environ[env_key] = prev
        else:
            os.environ.pop(env_key, None)

    try:
        salida = _probe(selection, api_key, timeout)
    except ModelNotAvailable as e:
        _restore_env()
        return False, f"Model “{selection.model}” isn't available: {e}"
    except Exception as e:
        _restore_env()
        return False, f"Couldn't reach {selection.provider.label}: {e}"
    if not (salida or "").strip():
        _restore_env()
        return False, f"{selection.provider.label} answered, but with nothing usable."
    return True, f"Connected to {selection.provider.label} using {selection.model}."
