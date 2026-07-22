"""La ventana de Shortcuts: que construya y que las etiquetas sean legibles.

Los tests instancian el controlador de AppKit de verdad, como los de
onboarding: eso valida que la ventana se construye sin reventar, que es el
fallo más caro y el más fácil de meter.

Lo que NO se puede validar aquí es que la ventana se VEA. En macOS 26 un
NSPanel devuelve isVisible=True y no pinta un solo píxel; por eso la ventana
es un NSWindow y por eso la verificación de que compone es manual, con
screencapture (ver el plan, Task 8 paso 6).
"""
from voooxly import settings_window, shortcuts, theme

ESTADO = {
    "dictation": {"keys": ["cmd_r"], "style": "hold", "delay_ms": 0},
    "cycle_mode": {"keys": ["ctrl", "shift", "m"]},
    "latch": {"keys": ["shift"]},
    "cancel": {"keys": ["esc"]},
}


def test_key_label_pinta_un_modificador_con_su_simbolo():
    assert settings_window.key_label(["cmd_r"]) == "⌘"
    assert settings_window.key_label(["shift"]) == "⇧"


def test_key_label_pinta_un_combo_en_orden():
    assert settings_window.key_label(["ctrl", "shift", "m"]) == "⌃⇧M"


def test_key_label_pinta_esc_y_las_funciones_por_su_nombre():
    assert settings_window.key_label(["esc"]) == "esc"
    assert settings_window.key_label(["f13"]) == "F13"


def test_key_label_de_una_lista_vacia_no_revienta():
    assert settings_window.key_label([]) == ""


def test_side_label_distingue_izquierda_y_derecha():
    # dictation y cancel casan por igualdad exacta en hotkey.py (líneas 397 y
    # 432): un nombre con lado siempre casa solo ese lado. La decisión vive en
    # shortcuts.side_hint; side_label es solo el envoltorio de presentación,
    # por eso necesita saber a qué atajo (sid) pertenece la tecla.
    assert settings_window.side_label("dictation", ["cmd_r"]) == "right"
    assert settings_window.side_label("dictation", ["cmd_l"]) == "left"
    assert settings_window.side_label("dictation", ["cmd"]) == "left"      # pynput colapsa la izquierda
    assert settings_window.side_label("cancel", ["esc"]) == ""


def test_side_label_pintado_dice_la_verdad_para_los_cuatro_atajos_por_defecto():
    """Las pruebas anteriores solo comprobaban que las filas existían, nunca
    el texto que de verdad se pintaba en pantalla — por eso hizo falta un
    screenshot para pescar que "Cycle mode" y "Latch dictation" mostraban
    "left" siendo mentira (un combo no tiene lado; el shift de latch casa las
    dos manos). Esto lee stringValue() de la etiqueta ya renderizada."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    esperado = {
        "dictation": "right",     # cmd_r: igualdad exacta, solo la derecha
        "cycle_mode": "",         # combo de tres teclas, sin lado
        "latch": "either side",   # "shift" ensancha a shift_r en hotkey.py
        "cancel": "",             # esc no tiene lado
    }
    for sid, texto in esperado.items():
        assert c._sides[sid].stringValue() == texto, sid
    c.close()


def test_el_controlador_construye():
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    assert c is not None
    c.close()


def test_construye_una_fila_por_atajo():
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    assert set(c._rows) == set(shortcuts.SHORTCUTS)
    c.close()


def test_la_etiqueta_de_lado_no_corta_either_side():
    """El bug real: el campo medía 58pt fijos, pensados para "right", y
    "either side" (el valor de latch de fábrica) mide más que eso con su
    propio font — el texto era correcto (stringValue() ya lo probaba) pero
    el glifo se recortaba en pantalla. Esto no puede probar que no se vea
    recortado (para eso hace falta un screenshot manual), pero sí puede
    reventar en cuanto el frame construido vuelva a quedarse corto para el
    texto que de verdad tiene que pintar."""
    from AppKit import NSFontAttributeName
    from Foundation import NSString

    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    campo = c._sides["latch"]
    ancho_texto = NSString.stringWithString_(campo.stringValue()).sizeWithAttributes_(
        {NSFontAttributeName: campo.font()}).width
    assert campo.frame().size.width >= ancho_texto, (
        campo.frame().size.width, ancho_texto)
    c.close()


def test_los_keycaps_quedan_alineados_en_las_cuatro_filas():
    """El ancho de la etiqueta de lado depende del font, no del texto de
    cada fila en concreto — hace falta el mismo hueco para "either side" en
    la fila de latch que en la de dictation, aunque esta última solo vaya a
    mostrar "right". Si cada fila calculase su propio ancho, la columna de
    keycaps quedaría escalonada; las cuatro comparten un x."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    xs = {sid: cap.frame().origin.x for sid, cap in c._keycaps.items()}
    assert len(set(xs.values())) == 1, xs
    c.close()


# Task 10, Defecto 2 (fix2): con cycle_mode en cinco teclas el keycap
# dibujaba ⌃⌥⇧⌘ y se tragaba la Q entera -_KEYCAP_W (62pt) se quedaba corto
# para el glifo real, medido con theme.text_width en 63,7pt, y la etiqueta
# interna de theme.keycap() iba centrada, así que un campo justo de ancho
# recortaba el último carácter sin que stringValue() se enterase.
_ESTADO_COMBO_LARGO = {**ESTADO, "cycle_mode": {"keys": ["ctrl", "alt", "shift", "cmd", "q"]}}


def test_el_keycap_de_un_combo_largo_mide_al_menos_su_texto():
    """El defecto real, reproducido: con cinco teclas a la vez el glifo mide
    más que los 62pt de siempre. Esto no puede probar que no se vea recortado
    en pantalla (para eso hace falta un screenshot manual, ver
    verificar-ventana.py), pero sí que el ancho reservado ya no se queda
    corto para lo que de verdad hay que pintar -sin clavar un ancho en
    píxeles, comparado contra theme.text_width() como el resto de anchos
    medidos de este módulo."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        _ESTADO_COMBO_LARGO, lambda sid, fila: (True, ""))
    texto = settings_window.key_label(_ESTADO_COMBO_LARGO["cycle_mode"]["keys"])
    necesita = theme.text_width(texto, theme.sf(14, 0.3))
    cap = c._keycaps["cycle_mode"]
    assert cap.frame().size.width >= necesita, (cap.frame().size.width, necesita)
    c.close()


def test_un_keycap_corto_conserva_el_ancho_minimo_aunque_otra_fila_sea_larga():
    """_KEYCAP_W (62pt) pasa a ser un SUELO, no un techo: los combos cortos
    de siempre (⌘ de dictation, esc de cancel) no cambian de tamaño -ni
    siquiera cuando OTRA fila (cycle_mode, aquí con cinco teclas) sí necesita
    más sitio-, o las filas bailarían cada vez que alguien reasigna un
    atajo distinto al suyo."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        _ESTADO_COMBO_LARGO, lambda sid, fila: (True, ""))
    for sid in ("dictation", "latch", "cancel"):
        assert c._keycaps[sid].frame().size.width == settings_window._KEYCAP_W, sid
    assert c._keycaps["cycle_mode"].frame().size.width > settings_window._KEYCAP_W
    c.close()


def test_el_keycap_largo_no_se_solapa_con_la_etiqueta_de_lado():
    """Al ensanchar el keycap para no recortar un combo largo, la fila tiene
    que seguir cuadrando: el borde derecho del keycap no puede pisar la
    etiqueta de lado. Se compara un marco contra el otro -no contra una
    constante de layout- para que la comprobación no dependa de que
    _LADO_GAP siga valiendo lo mismo mañana."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        _ESTADO_COMBO_LARGO, lambda sid, fila: (True, ""))
    for sid in shortcuts.SHORTCUTS:
        cap = c._keycaps[sid]
        lado = c._sides[sid]
        assert cap.frame().origin.x + cap.frame().size.width <= lado.frame().origin.x, (
            sid, cap.frame(), lado.frame())
    c.close()


def test_la_ventana_es_un_nswindow_no_un_nspanel():
    # En macOS 26 (Darwin 25) el window server NUNCA compone un NSPanel:
    # isVisible=True, alpha=1, CGWindowList vacío y cero píxeles. El HUD
    # estuvo roto en silencio por esto. Un test barato que impide la recaída.
    from AppKit import NSPanel

    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    assert not isinstance(c._win, NSPanel)
    c.close()
