"""El campo de chips estilo Wispr Flow y el Reset to defaults.

Del feedback de Eduardo (con capturas de Wispr): cada tecla del atajo es su
PROPIO chip dentro de un campo con un lápiz ✎ al final; al capturar, lo que
pulsas se refleja en vivo en el campo Y en el teclado; y un botón devuelve
todo a fábrica. Los tests instancian el controlador de AppKit real, como el
resto de tests de esta ventana.
"""
from PyObjCTools import AppHelper

from voooxly import settings_window, shortcuts, theme

ESTADO = {
    "dictation": {"keys": ["cmd_r"], "style": "hold", "delay_ms": 0},
    "cycle_mode": {"keys": ["ctrl", "shift", "m"]},
    "latch": {"keys": ["shift"]},
    "cancel": {"keys": ["esc"]},
}


def _ctl(estado=None, on_change=None):
    return settings_window.ShortcutsController.alloc().initWithState_onChange_(
        estado or ESTADO, on_change or (lambda sid, fila: (True, "")))


def test_chip_texts_da_un_chip_por_tecla():
    assert settings_window.chip_texts(["ctrl", "shift", "m"]) == ["⌃", "⇧", "M"]
    assert settings_window.chip_texts(["fn"]) == ["fn"]
    assert settings_window.chip_texts([]) == []


def test_cada_fila_pinta_un_chip_por_tecla_de_su_binding():
    c = _ctl()
    assert len(c._chips["cycle_mode"]) == 3
    assert len(c._chips["dictation"]) == 1
    # El texto del chip sale de key_label tecla a tecla: la subvista única
    # del keycap de theme lleva el glifo.
    textos = [chip.subviews()[0].stringValue() for chip in c._chips["cycle_mode"]]
    assert textos == ["⌃", "⇧", "M"]
    c.close()


def test_cada_campo_lleva_su_lapiz():
    # El lápiz ES la afordancia de editar (el "Change" de antes no se
    # identificaba como acción): tiene que estar en las cuatro filas.
    c = _ctl()
    for sid in shortcuts.SHORTCUTS:
        assert c._pencils[sid].stringValue() == settings_window._PENCIL_TXT, sid
    c.close()


def test_al_capturar_el_campo_muestra_el_placeholder_hasta_la_primera_tecla():
    c = _ctl()
    assert c._hints["dictation"].isHidden()
    c.begin_capture_("dictation")
    assert not c._hints["dictation"].isHidden()
    assert c._chips["dictation"] == []          # sin teclas aún: campo vacío
    assert c._hints["cancel"].isHidden()        # solo la fila en captura
    c.close()


def test_la_fila_en_captura_se_resalta_entera():
    c = _ctl()
    c.begin_capture_("latch")
    assert c._rows["latch"].layer().backgroundColor() == theme.MODEL_BTN_BG.CGColor()
    assert c._rows["cancel"].layer().backgroundColor() == theme.PAGE_BG.CGColor()
    c.cancel_capture_()
    assert c._rows["latch"].layer().backgroundColor() == theme.PAGE_BG.CGColor()
    c.close()


def test_lo_pulsado_se_refleja_en_chips_y_en_el_teclado(monkeypatch):
    """El corazón del feedback: "si marco el shortcut que se refleje en el
    teclado". Una letra suelta no valida como atajo de dictado (inutilizaría
    el teclado entero), pero el chip X aparece en el campo y su casilla sube
    a TEAL_DARK — el usuario VE que la pulsación llegó aunque no sea un
    atajo válido, y la captura sigue armada para que lo intente de nuevo."""
    monkeypatch.setattr(AppHelper, "callAfter", lambda fn, *a, **kw: fn(*a, **kw))
    c = _ctl()
    c.begin_capture_("dictation")
    c._on_captured_(["x"])
    assert c._capturing == "dictation"          # validate rechazó: sigue armada
    textos = [chip.subviews()[0].stringValue() for chip in c._chips["dictation"]]
    assert textos == ["X"]
    assert c._keys["x"].layer().backgroundColor() == theme.TEAL_DARK.CGColor()
    assert c._legends["x"].textColor().isEqual_(theme.PAGE_BG)
    c.close()


def test_una_captura_valida_deja_los_chips_del_binding_nuevo():
    c = _ctl()
    c.begin_capture_("cancel")
    c.apply_capture_(["f13"])
    textos = [chip.subviews()[0].stringValue() for chip in c._chips["cancel"]]
    assert textos == ["F13"]
    assert c._hints["cancel"].isHidden()
    c.close()


def test_reset_devuelve_los_cuatro_atajos_a_fabrica():
    cambiados = dict(
        ESTADO,
        dictation={"keys": ["f13"], "style": "hold", "delay_ms": 600},
        cancel={"keys": ["ctrl", "shift"]},
    )
    vistos = []
    c = _ctl(cambiados, lambda sid, fila: (vistos.append(sid), (True, ""))[1])
    c.resetDefaults_(None)
    for sid, sc in shortcuts.SHORTCUTS.items():
        assert c._estado[sid]["keys"] == list(sc.default), sid
    # cmd_r no necesita guarda: el delay de fábrica es 0, no los 600 de antes.
    assert c._estado["dictation"]["delay_ms"] == 0
    assert set(vistos) == set(shortcuts.SHORTCUTS)
    c.close()


def test_reset_cancela_una_captura_a_medias():
    c = _ctl()
    c.begin_capture_("dictation")
    c.resetDefaults_(None)
    assert c._capturing is None
    c.close()
