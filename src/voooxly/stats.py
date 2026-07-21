"""Stats de uso: cuántos dictados, cuántas palabras, cuánto tecleo ahorrado.

Contadores acumulativos en ~/.voooxly/stats.json (no rota: son 3 números).
El "typing saved" compara hablar (~150 wpm reales dictando) con teclear
(~40 wpm de un tecleo medio): words/40 − words/150 minutos. Best-effort:
unas stats rotas jamás estorban al dictado.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("voooxly.stats")

STATS_FILE = Path.home() / ".voooxly" / "stats.json"

TYPING_WPM = 40
SPEAKING_WPM = 150


def load(path: Path | None = None) -> dict:
    path = path or STATS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "dictations": int(data.get("dictations", 0)),
            "words": int(data.get("words", 0)),
            "seconds_recorded": float(data.get("seconds_recorded", 0.0)),
            # Claves nuevas con default: un stats.json de una versión anterior
            # se sigue leyendo entero en vez de perderse.
            "tokens": int(data.get("tokens", 0)),
            "token_provider": str(data.get("token_provider", "")),
        }
    except Exception:
        return {
            "dictations": 0,
            "words": 0,
            "seconds_recorded": 0.0,
            "tokens": 0,
            "token_provider": "",
        }


def bump(words: int, seconds: float, path: Path | None = None) -> None:
    path = path or STATS_FILE
    try:
        s = load(path)
        s["dictations"] += 1
        s["words"] += max(0, int(words))
        s["seconds_recorded"] += max(0.0, float(seconds))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(s) + "\n", encoding="utf-8")
    except Exception as e:
        log.debug("No pude actualizar las stats: %s", e)


def bump_tokens(tokens: int, provider: str, path: Path | None = None) -> None:
    """Acumula los tokens gastados en el LLM remoto.

    Sirve para que quien use un free tier (Groq) vea cuánto lleva consumido
    sin salir de la app. Ollama no llega aquí: es local y no gasta cuota, y un
    contador a 0 junto a "free tier" solo confunde.
    """
    path = path or STATS_FILE
    try:
        s = load(path)
        s["tokens"] += max(0, int(tokens))
        s["token_provider"] = provider or s["token_provider"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(s) + "\n", encoding="utf-8")
    except Exception as e:
        log.debug("No pude actualizar los tokens: %s", e)


def summary(path: Path | None = None) -> str:
    s = load(path)
    if not s["dictations"]:
        return "No dictations yet — hold the key and speak."
    saved_min = s["words"] * (1 / TYPING_WPM - 1 / SPEAKING_WPM)
    saved = f"~{saved_min / 60:.1f} h" if saved_min >= 60 else f"~{round(saved_min)} min"
    out = (
        f"{s['dictations']} dictations · {s['words']:,} words · "
        f"{saved} of typing saved"
    )
    if s["tokens"]:
        cifra = _formato_tokens(s["tokens"])
        quien = f" · {s['token_provider']}" if s["token_provider"] else ""
        out += f"\n~{cifra} tokens{quien}"
    return out


def _formato_tokens(tokens: int) -> str:
    """"k"/"M" según magnitud, sin que el redondeo desborde la escala.

    Redondear en "k" cerca de un millón (p.ej. 999.500 → 999.5k → "1000k" con
    .0f) produce una escala que no existe: "1000k" debería ser "1M". Por eso
    la promoción a M se decide DESPUÉS de redondear, no antes.
    """
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1000:
        miles = round(tokens / 1000)
        if miles >= 1000:  # el redondeo empujó a la escala de millón
            return f"{tokens / 1_000_000:.1f}M"
        return f"{miles}k"
    return f"{tokens}"
