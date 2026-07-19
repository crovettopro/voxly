"""Stats de uso: cuántos dictados, cuántas palabras, cuánto tecleo ahorrado.

Contadores acumulativos en ~/.dictador/stats.json (no rota: son 3 números).
El "typing saved" compara hablar (~150 wpm reales dictando) con teclear
(~40 wpm de un tecleo medio): words/40 − words/150 minutos. Best-effort:
unas stats rotas jamás estorban al dictado.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("dictador.stats")

STATS_FILE = Path.home() / ".dictador" / "stats.json"

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
        }
    except Exception:
        return {"dictations": 0, "words": 0, "seconds_recorded": 0.0}


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


def summary(path: Path | None = None) -> str:
    s = load(path)
    if not s["dictations"]:
        return "No dictations yet — hold the key and speak."
    saved_min = s["words"] * (1 / TYPING_WPM - 1 / SPEAKING_WPM)
    saved = f"~{saved_min / 60:.1f} h" if saved_min >= 60 else f"~{round(saved_min)} min"
    return (
        f"{s['dictations']} dictations · {s['words']:,} words · "
        f"{saved} of typing saved"
    )
