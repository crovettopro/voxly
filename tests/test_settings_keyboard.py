"""El teclado dibujado: qué teclas se encienden y de parte de quién.

El teclado y la lista son la MISMA verdad. Si divergen, el usuario ve una
tecla encendida que la lista dice que no está asignada y deja de fiarse de
las dos. Por eso lit_keys() sale del mismo estado que pinta la lista.
"""
from voooxly import settings_window

ESTADO = {
    "dictation": {"keys": ["cmd_r"], "style": "hold", "delay_ms": 0},
    "cycle_mode": {"keys": ["ctrl", "shift", "m"]},
    "latch": {"keys": ["shift"]},
    "cancel": {"keys": ["esc"]},
}


def test_se_encienden_todas_las_teclas_asignadas():
    lit = settings_window.lit_keys(ESTADO)
    assert lit["cmd_r"] == "dictation"
    assert lit["esc"] == "cancel"
    assert lit["m"] == "cycle_mode"


def test_una_tecla_compartida_la_reclama_dictation():
    # ⇧ es el latch y también parte de ⌃⇧M. Dictation manda sobre el resto
    # porque es la tecla que el usuario busca de un vistazo; sin una regla de
    # desempate el color dependería del orden del diccionario.
    estado = dict(ESTADO, dictation={"keys": ["shift"], "style": "hold", "delay_ms": 400})
    assert settings_window.lit_keys(estado)["shift"] == "dictation"


def test_las_teclas_se_canonicalizan_antes_de_encenderse():
    # "cmd_l" y "cmd" son la misma tecla física: el teclado tiene que
    # encender la misma casilla en los dos casos o el usuario ve su tecla
    # apagada tras elegirla.
    estado = dict(ESTADO, dictation={"keys": ["cmd_l"], "style": "hold", "delay_ms": 400})
    lit = settings_window.lit_keys(estado)
    assert "cmd" in lit


def test_el_teclado_tiene_las_seis_filas_de_un_mac():
    assert len(settings_window.KEYBOARD_ROWS) == 6


def test_el_teclado_incluye_las_teclas_que_importan():
    todas = {n for fila in settings_window.KEYBOARD_ROWS for n, _ in fila if n}
    for n in ("esc", "cmd_r", "cmd", "shift", "ctrl", "alt", "m", "f13"):
        assert n in todas, n


def test_pintar_el_teclado_no_revienta():
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    c._paint_keyboard()
    assert len(c._keys) > 40
    c.close()
