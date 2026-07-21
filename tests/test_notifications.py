"""Entrega de avisos al usuario.

Contexto: en macOS 26 la API legacy NSUserNotification (la que usa
rumps.notification) NO entrega nada. Voooxly ni siquiera aparece en
com.apple.ncprefs.plist, así que los avisos se descartaban en silencio —
"Backend status" y "Usage stats" no hacían nada porque el aviso ERA la
función entera. Estos tests impiden que la API muerta vuelva a colarse.
"""

import re
from pathlib import Path

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


# health_summary() y "Backend status…" se retiraron: el submenú AI engine ya
# lleva el motor activo en su propio título ("AI engine — Groq"), así que el
# modal decía lo mismo con jerga de backends. refine.health() sigue viva —
# setup_checks y `launch.sh --check` la usan.
