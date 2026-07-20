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
import threading
import time

log = logging.getLogger("voooxly.output")


def copy_to_clipboard(text: str, html: str | None = None) -> None:
    if not text:
        return
    # NSPasteboard directo: pbcopy interpreta stdin según LANG/LC_CTYPE, y al
    # lanzar la .app desde Finder no hay locale -> asume Mac Roman y rompe las
    # tildes (í -> √≠). Escribir el NSString evita la codificación por completo.
    # Si llega `html`, se añade como segundo sabor (public.html): las apps de
    # texto rico (Mail, Gmail, Notion) pegan títulos/listas renderizados y las
    # de texto plano (Terminal, Obsidian, IDEs) siguen tomando el plano.
    try:
        from AppKit import NSPasteboard, NSPasteboardTypeString

        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(text, NSPasteboardTypeString)
        if html:
            pb.setString_forType_(html, "public.html")
    except Exception as e:
        log.error("NSPasteboard falló (%s); fallback a pbcopy", e)
        try:
            env = {**os.environ, "LC_CTYPE": "UTF-8"}
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), env=env, check=True)
        except Exception as e2:
            log.error("pbcopy falló: %s", e2)


_kb = None
_kb_lock = threading.Lock()


def _controller():
    """El Controller de pynput, construido UNA sola vez.

    Su __init__ consulta la distribución de teclado vía TIS/TSM. Construirlo en
    cada pegado (desde el hilo worker de _process) lo hacía coincidir tarde o
    temprano con otro hilo tocando TSM —el listener del hotkey— y entonces
    HIToolbox mata el proceso: SIGTRAP en dispatch_assert_queue, que NO es una
    excepción de Python y ningún try/except puede atrapar.

    press()/release() solo usan el mapping ya cacheado y CGEventPost, así que
    con una única construcción el pegado deja de tocar TSM. Ver warmup().
    """
    global _kb
    with _kb_lock:
        if _kb is None:
            from pynput.keyboard import Controller

            _kb = Controller()
        return _kb


def warmup() -> bool:
    """Paga el coste de TSM al arrancar, desde el main thread y sin hilos aún vivos."""
    try:
        _controller()
        return True
    except Exception as e:
        log.warning("No pude preparar el teclado para pegar: %s", e)
        return False


def paste_frontmost() -> bool:
    """Simula Cmd+V en la app activa posteando eventos de teclado (Accesibilidad)."""
    try:
        from pynput.keyboard import Key

        kb = _controller()
        kb.press(Key.cmd)
        kb.press("v")
        time.sleep(0.02)
        kb.release("v")
        kb.release(Key.cmd)
        return True
    except Exception as e:
        log.error("Paste falló (¿Accesibilidad concedida?): %s", e)
        return False


def deliver(text: str, auto_paste: bool, copy: bool, html: str | None = None) -> str:
    """Entrega el texto y devuelve cómo quedó, para que la UI pueda avisar:

    - "pasted": pegado en la app activa (lo normal).
    - "copied": no se pegó, pero está en el portapapeles (⌘V manual).
    - "failed": ni pegado ni copiado.
    """
    if not text:
        return "failed"
    if copy:
        copy_to_clipboard(text, html)
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
