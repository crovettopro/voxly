"""Output: copiar al portapapeles y/o pegar en la app activa con Cmd+V.

El pegado simula Cmd+V posteando eventos CGEvent vía pynput.Controller. Eso queda
cubierto por el permiso de Accesibilidad (que la app ya necesita para el hotkey).
NO usamos osascript/System Events: requiere el permiso de Automatización
(NSAppleEventsUsageDescription + prompt aparte) y sin él se cuelga hasta timeout.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time

log = logging.getLogger("dictador.output")


def copy_to_clipboard(text: str) -> None:
    if not text:
        return
    # NSPasteboard directo: pbcopy interpreta stdin según LANG/LC_CTYPE, y al
    # lanzar la .app desde Finder no hay locale -> asume Mac Roman y rompe las
    # tildes (í -> √≠). Escribir el NSString evita la codificación por completo.
    try:
        from AppKit import NSPasteboard, NSPasteboardTypeString

        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(text, NSPasteboardTypeString)
    except Exception as e:
        log.error("NSPasteboard falló (%s); fallback a pbcopy", e)
        try:
            env = {**os.environ, "LC_CTYPE": "UTF-8"}
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), env=env, check=True)
        except Exception as e2:
            log.error("pbcopy falló: %s", e2)


def paste_frontmost() -> bool:
    """Simula Cmd+V en la app activa posteando eventos de teclado (Accesibilidad)."""
    try:
        from pynput.keyboard import Controller, Key

        kb = Controller()
        kb.press(Key.cmd)
        kb.press("v")
        time.sleep(0.02)
        kb.release("v")
        kb.release(Key.cmd)
        return True
    except Exception as e:
        log.error("Paste falló (¿Accesibilidad concedida?): %s", e)
        return False


def deliver(text: str, auto_paste: bool, copy: bool) -> str:
    """Entrega el texto y devuelve cómo quedó, para que la UI pueda avisar:

    - "pasted": pegado en la app activa (lo normal).
    - "copied": no se pegó, pero está en el portapapeles (⌘V manual).
    - "failed": ni pegado ni copiado.
    """
    if not text:
        return "failed"
    if copy:
        copy_to_clipboard(text)
    if auto_paste:
        # pequeño delay para que el portapapeles se asiente
        time.sleep(0.08)
        ok = paste_frontmost()
        if ok:
            return "pasted"
        if copy:
            log.info("Texto dejado en portapapeles (pega manual Cmd+V).")
            return "copied"
        return "failed"
    return "copied" if copy else "failed"
