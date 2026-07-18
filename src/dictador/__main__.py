"""Punto de entrada: `python -m dictador` o `dictador` tras instalar."""
from __future__ import annotations

import argparse
import logging
import sys

from .config import get_config


def _setup_logging(level: str):
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    # en .app bundle (console=False) stderr se pierde -> log también a archivo
    try:
        import os
        from pathlib import Path

        log_dir = Path.home() / ".dictador" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / "dictador.log", encoding="utf-8"))
    except Exception:
        pass
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )


def main():
    p = argparse.ArgumentParser(prog="dictador", description="Dictado local pro tipo Wispr Flow.")
    p.add_argument("--check", action="store_true", help="Verifica deps y backends y sale.")
    p.add_argument("--devices", action="store_true", help="Lista dispositivos de entrada y sale.")
    p.add_argument("--onboarding", action="store_true",
                   help="Muestra el asistente de primer arranque y sale (para probarlo).")
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

    if args.onboarding:
        from AppKit import NSApplication
        from PyObjCTools import AppHelper

        from .onboarding import show_onboarding

        NSApplication.sharedApplication()
        show_onboarding(on_finish=AppHelper.stopEventLoop)
        AppHelper.runEventLoop()
        return

    # arranca la app de menú
    from .app import DictadorApp

    DictadorApp().run()


if __name__ == "__main__":
    main()