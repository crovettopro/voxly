"""Output: copiar al portapapeles y/o pegar en la app activa con Cmd+V."""
from __future__ import annotations

import logging
import subprocess

log = logging.getLogger("dictador.output")


def copy_to_clipboard(text: str) -> None:
    if not text:
        return
    try:
        p = subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        _ = p
    except Exception as e:
        log.error("pbcopy falló: %s", e)


def paste_frontmost(timeout: float = 0.2) -> bool:
    """Simula Cmd+V en la app activa vía System Events. Requiere permisos de
    Accesibilidad y Automatización. Devuelve True si el AppleScript ejecutó."""
    script = '''
    tell application "System Events"
        keystroke "v" using command down
    end tell
    '''
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            timeout=5,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        log.error("Paste falló (Automatización/Accesibilidad?). %s", e.stderr.decode("utf-8", "ignore"))
        return False
    except Exception as e:
        log.error("Paste falló: %s", e)
        return False


def deliver(text: str, auto_paste: bool, copy: bool) -> None:
    if not text:
        return
    if copy:
        copy_to_clipboard(text)
    if auto_paste:
        # pequeño delay para que el portapapeles se asiente
        import time

        time.sleep(0.05)
        ok = paste_frontmost()
        if not ok and copy:
            log.info("Texto dejado en portapapeles (pega manual Cmd+V).")