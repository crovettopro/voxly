"""Capturar una tecla desde la ventana y ajustar el delay.

La regla que más cuesta acertar es el salto automático del slíder: elegir el
⌘ izquierdo con 0 ms deja la app inservible (cada ⌘C arranca una grabación),
así que el slíder salta a 400 solo. Pero elegir el ⌘ derecho NO puede subir a
nadie de 0 a 400: sería cambiarle el tacto de la app por la cara.
"""
from voooxly import settings_window, shortcuts

ESTADO = {
    "dictation": {"keys": ["cmd_r"], "style": "hold", "delay_ms": 0},
    "cycle_mode": {"keys": ["ctrl", "shift", "m"]},
    "latch": {"keys": ["shift"]},
    "cancel": {"keys": ["esc"]},
}


def _ctl(on_change=None):
    return settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, on_change or (lambda sid, fila: (True, "")))


def test_una_tecla_conflictiva_sube_el_delay_al_default():
    assert settings_window.delay_for(["cmd_l"], 0) == shortcuts.DEFAULT_DELAY_MS


def test_una_tecla_sin_conflicto_conserva_el_delay_anterior():
    # Cero regresión: quien tenía 0 con ⌘ derecho sigue con 0.
    assert settings_window.delay_for(["cmd_r"], 0) == 0


def test_una_tecla_sin_conflicto_no_baja_un_delay_ya_elegido():
    # Si el usuario había puesto 600 a mano, cambiar de tecla no se lo pisa.
    assert settings_window.delay_for(["cmd_r"], 600) == 600


def test_capturar_aplica_la_tecla_y_avisa_al_llamador():
    visto = []
    c = _ctl(lambda sid, fila: (visto.append((sid, fila)), (True, ""))[1])
    c.begin_capture_("cancel")
    c.apply_capture_(["f13"])
    assert visto[-1][0] == "cancel"
    assert visto[-1][1]["keys"] == ["f13"]
    c.close()


def test_una_tecla_en_conflicto_no_se_aplica():
    visto = []
    c = _ctl(lambda sid, fila: (visto.append(sid), (True, ""))[1])
    c.begin_capture_("dictation")
    c.apply_capture_(["esc"])          # ya es la de cancelar
    assert visto == [], "se aplicó una tecla en conflicto"
    assert c._estado["dictation"]["keys"] == ["cmd_r"]
    c.close()


def test_una_tecla_en_conflicto_deja_mensaje_en_la_fila():
    c = _ctl()
    c.begin_capture_("dictation")
    c.apply_capture_(["esc"])
    assert "Cancel dictation" in c._error_text
    c.close()


def test_si_el_llamador_rechaza_el_cambio_el_estado_no_se_toca():
    # on_change devuelve (False, msg) cuando hotkey.rebind() rechaza: el
    # estado de la ventana tiene que reflejar lo que suena de verdad, no lo
    # que se pidió, o el keycap mentiría.
    c = _ctl(lambda sid, fila: (False, "nope"))
    c.begin_capture_("cancel")
    c.apply_capture_(["f13"])
    assert c._estado["cancel"]["keys"] == ["esc"]
    assert c._error_text == "nope"
    c.close()


def test_cancelar_la_captura_deja_el_atajo_como_estaba():
    c = _ctl()
    c.begin_capture_("dictation")
    c.cancel_capture_()
    assert c._estado["dictation"]["keys"] == ["cmd_r"]
    assert c._capturing is None
    c.close()


def test_el_delay_se_recorta_al_rango():
    c = _ctl()
    c.set_delay_(9999)
    assert c._estado["dictation"]["delay_ms"] == shortcuts.MAX_DELAY_MS
    c.set_delay_(-5)
    assert c._estado["dictation"]["delay_ms"] == 0
    c.close()


def test_capturar_repinta_el_teclado():
    c = _ctl()
    c.begin_capture_("cancel")
    c.apply_capture_(["f13"])
    assert settings_window.lit_keys(c._estado)["f13"] == "cancel"
    c.close()
