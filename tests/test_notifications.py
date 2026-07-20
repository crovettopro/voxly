"""Entrega de avisos al usuario.

Contexto: en macOS 26 la API legacy NSUserNotification (la que usa
rumps.notification) NO entrega nada. Voooxly ni siquiera aparece en
com.apple.ncprefs.plist, así que los avisos se descartaban en silencio —
"Backend status" y "Usage stats" no hacían nada porque el aviso ERA la
función entera. Estos tests impiden que la API muerta vuelva a colarse.
"""

import re
from pathlib import Path

import pytest

from voooxly import refine

SRC = Path(__file__).resolve().parent.parent / "src" / "voooxly"


def test_no_queda_ningun_rumps_notification_en_el_codigo():
    """rumps.notification no entrega en macOS 26: cualquier uso es un aviso perdido."""
    culpables = []
    for py in SRC.rglob("*.py"):
        for n, linea in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            codigo = linea.split("#", 1)[0]  # los comentarios SÍ pueden nombrarla
            if re.search(r"\brumps\.notification\s*\(", codigo):
                culpables.append(f"{py.name}:{n}")
    assert not culpables, (
        "rumps.notification no se entrega en macOS 26 — usa _alert() (modal, "
        f"para info que el usuario ha pedido) o _hud() (efímero): {culpables}"
    )


# --- health_summary: el texto que ve el usuario en "Backend status…" ---


def test_health_summary_marca_disponibles_y_caidos(monkeypatch):
    monkeypatch.setattr(refine, "health", lambda: {"ollama": True, "claude": False})
    resumen = refine.health_summary()
    assert "ollama" in resumen and "claude" in resumen
    assert "✓" in resumen and "✗" in resumen


def test_health_summary_con_todo_caido_no_lanza(monkeypatch):
    monkeypatch.setattr(refine, "health", lambda: {"ollama": False})
    assert "✗" in refine.health_summary()


def test_health_summary_sin_backends_da_texto_util(monkeypatch):
    """Un dict vacío no puede producir una cadena vacía: el usuario vería un modal en blanco."""
    monkeypatch.setattr(refine, "health", lambda: {})
    assert refine.health_summary().strip()
