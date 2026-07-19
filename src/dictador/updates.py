"""Actualizaciones: consulta un appcast.json, compara versiones y descarga el DMG.

Si hay versión nueva, la app muestra un ítem de menú; el clic descarga el DMG a
~/Downloads y lo abre montado — al usuario solo le queda arrastrar a
Applications. Sin auto-reemplazo silencioso: Sparkle sobre un bundle PyInstaller
da más problemas que valor, y Gatekeeper ya verifica el DMG notarizado.

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

# OJO: voxly.vercel.app pertenece a OTRO usuario de Vercel; nuestro dominio
# de producción es usevoxly.vercel.app (proyecto "voxly" de crovettopro).
APPCAST_URL = "https://usevoxly.vercel.app/appcast.json"
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


def download(
    url: str,
    version: str,
    dest_dir: Path | None = None,
    progress_cb=None,
) -> Path | None:
    """Descarga el DMG a `dest_dir` (~/Downloads por defecto). Ruta o None.

    Se baja a un .part y se renombra al terminar: nunca queda un DMG a medias
    con el nombre final. Cualquier fallo devuelve None y limpia el .part.
    `progress_cb(pct)` recibe 0-100 si el servidor manda Content-Length.
    """
    dest_dir = dest_dir or Path.home() / "Downloads"
    dest = dest_dir / f"Voxly-{version}.dmg"
    part = dest_dir / (dest.name + ".part")
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            with open(part, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb and total:
                        progress_cb(min(99, done * 100 // total))
        part.replace(dest)
        if progress_cb:
            progress_cb(100)
        log.info("Update descargada: %s", dest)
        return dest
    except Exception as e:
        log.warning("Descarga de update falló: %s", e)
        try:
            part.unlink(missing_ok=True)
        except Exception:
            pass
        return None
