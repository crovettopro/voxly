"""Aviso de actualizaciones: consulta un appcast.json y compara versiones.

Sin auto-instalación: si hay versión nueva, la app muestra un ítem de menú que
abre la URL de descarga. Sparkle sobre un bundle PyInstaller da más problemas
que valor para lo que aporta aquí.

Cualquier fallo (sin red, JSON roto, campos ausentes) es silencioso salvo en el
log: un comprobador de updates roto jamás debe estorbar al dictado.
"""
from __future__ import annotations

import logging
import plistlib
import sys
from pathlib import Path

import requests

log = logging.getLogger("dictador.updates")

APPCAST_URL = "https://voxly.vercel.app/appcast.json"
# Fuera del .app (ejecutando desde el repo) no hay Info.plist del que leer.
FALLBACK_VERSION = "1.0.0"


def _parse(v: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(p) for p in str(v).strip().split("."))
    except (ValueError, AttributeError):
        return None


def is_newer(remote: str, local: str) -> bool:
    """True si `remote` es una versión posterior a `local`.

    Compara por componentes numéricos: "1.10.0" es mayor que "1.9.0", cosa que
    una comparación de cadenas se equivocaría.
    """
    r, l = _parse(remote), _parse(local)
    if r is None or l is None:
        return False
    n = max(len(r), len(l))
    return r + (0,) * (n - len(r)) > l + (0,) * (n - len(l))


def current_version() -> str:
    """Versión del bundle leída del Info.plist; FALLBACK_VERSION fuera del .app."""
    try:
        exe = Path(sys.executable).resolve()
        for parent in exe.parents:
            plist = parent / "Info.plist"
            if plist.exists():
                data = plistlib.loads(plist.read_bytes())
                v = data.get("CFBundleShortVersionString")
                if v:
                    return str(v)
    except Exception:
        pass
    return FALLBACK_VERSION


def check(url: str = APPCAST_URL, local: str | None = None) -> dict | None:
    """Devuelve {version, url, notes} si hay una versión más nueva; None si no."""
    local = local or current_version()
    try:
        r = requests.get(url, timeout=8)
        if not r.ok:
            return None
        data = r.json()
        remote = data.get("version")
        dmg = data.get("url")
        if not remote or not dmg or not is_newer(str(remote), local):
            return None
        log.info("Update disponible: %s (instalada: %s)", remote, local)
        return {
            "version": str(remote),
            "url": str(dmg),
            "notes": str(data.get("notes", "")),
        }
    except Exception as e:
        log.debug("Comprobación de updates falló (ignorado): %s", e)
        return None
