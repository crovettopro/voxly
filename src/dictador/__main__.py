"""Punto de entrada: `python -m dictador` o `dictador` tras instalar."""
from __future__ import annotations

import argparse
import logging
import sys

from .config import get_config


def _setup_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    p = argparse.ArgumentParser(prog="dictador", description="Dictado local pro tipo Wispr Flow.")
    p.add_argument("--check", action="store_true", help="Verifica deps y backends y sale.")
    p.add_argument("--devices", action="store_true", help="Lista dispositivos de entrada y sale.")
    p.add_argument("--log", default=None, help="Nivel de log (DEBUG/INFO/WARNING)")
    args = p.parse_args()

    cfg = get_config()
    level = args.log or cfg.get("app.log_level", "INFO")
    _setup_logging(level)

    if args.devices:
        from . import audio

        for d in audio.list_input_devices():
            print(f"{d['index']}: {d['name']} ({d['channels']}ch)")
        return

    if args.check:
        from . import refine, stt

        print("Backends LLM:", refine.health())
        print("STT available (whisper.cpp):", stt.is_available())
        print("STT model cfg:", cfg.get("stt.model"))
        return

    # arranca la app de menú
    from .app import DictadorApp

    DictadorApp().run()


if __name__ == "__main__":
    main()