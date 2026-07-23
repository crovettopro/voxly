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

log = logging.getLogger("voooxly.updates")

# OJO: voooxly.vercel.app pertenece a OTRO usuario de Vercel; nuestro dominio
# de producción es voooxly.com (proyecto "voooxly" de crovettopro).
APPCAST_URL = "https://voooxly.com/appcast.json"
# Fuera del .app (ejecutando desde el repo) no hay Info.plist del que leer.
FALLBACK_VERSION = "1.5.0"

# Re-chequeo periódico: la app vuelve a consultar cada CHECK_INTERVAL segundos
# mientras esté abierta (además del check al arranque). 24 h cubre a quien la
# deja abierta días/semanas sin martilleo.
CHECK_INTERVAL = 24 * 3600

# Estados de check_status(): check() colapsa "sin novedad" y "error" en None,
# que basta para el check periódico silencioso. El botón manual necesita
# distinguirlos para decirle al usuario cuál de las dos pasó.
UPDATE_AVAILABLE = "available"
UP_TO_DATE = "up_to_date"
UPDATE_ERROR = "error"


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
    """Devuelve {version, url, notes} si hay una versión más nueva; None si no.

    Wrapper fino sobre check_status() para el check periódico, que reacciona
    solo a "hay novedad" y trata error y "estás al día" igual (silencio). El
    botón manual usa check_status() para poder distinguirlos.
    """
    status, info = check_status(url, local)
    return info if status == UPDATE_AVAILABLE else None


def check_status(
    url: str = APPCAST_URL, local: str | None = None
) -> tuple[str, dict | None]:
    """Como check() pero distingue "sin novedad" de "error de red".

    Devuelve (status, info); info solo cuando status == UPDATE_AVAILABLE.
    Cualquier fallo (sin red, JSON roto, campos ausentes, HTTP error) es
    UPDATE_ERROR, nunca lanza — un comprobador roto no debe estorbar.
    """
    local = local or current_version()
    try:
        r = requests.get(url, timeout=8)
        if not r.ok:
            return UPDATE_ERROR, None
        data = r.json()
        remote = data.get("version")
        dmg = data.get("url")
        if not remote or not dmg:
            return UPDATE_ERROR, None
        if is_newer(str(remote), local):
            log.info("Update disponible: %s (instalada: %s)", remote, local)
            return UPDATE_AVAILABLE, {
                "version": str(remote),
                "url": str(dmg),
                "notes": str(data.get("notes", "")),
            }
        return UP_TO_DATE, None
    except Exception as e:
        log.debug("Comprobación de updates falló (ignorado): %s", e)
        return UPDATE_ERROR, None


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
    dest = dest_dir / f"Voooxly-{version}.dmg"
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


def should_notify(info: dict | None, already_notified: str | None) -> bool:
    """True si hay novedad Y no avisamos ya para esta versión.

    El aviso del re-chequeo periódico sale una sola vez por versión: si la app
    lleva abierta 5 días y la 1.3.0 sale el día 1, no se anuncia de nuevo cada
    24 h. Cuando suba a 1.4.0, sí.
    """
    return bool(info) and info["version"] != already_notified


def should_prompt(info: dict | None, prompted_version: str | None) -> bool:
    """True si hay novedad Y el pop-up de esa versión no se enseñó ya.

    Misma aritmética que should_notify pero con otra vida: aquí
    `prompted_version` viene de prefs.json, así que el alert de "Update
    available" no se repite en cada arranque mientras el usuario decide
    esperar. Cuando salga una versión más nueva, vuelve a preguntar.
    """
    return bool(info) and info["version"] != prompted_version
