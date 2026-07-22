"""El teclado dibujado: qué teclas se encienden y de parte de quién.

El teclado y la lista son la MISMA verdad. Si divergen, el usuario ve una
tecla encendida que la lista dice que no está asignada y deja de fiarse de
las dos. Por eso lit_keys() sale del mismo estado que pinta la lista.
"""
from voooxly import settings_window, shortcuts, theme

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


def test_lit_keys_y_side_hint_cuentan_la_misma_verdad_sobre_los_lados():
    """Defecto 1 de la Task 9: side_hint() (el texto de la fila) y lit_keys()
    (las casillas que se encienden) eran dos implementaciones independientes
    del mismo hecho runtime y se podían desincronizar. El bug real: con el
    latch de fábrica (shift), la fila decía "either side" pero el teclado
    solo encendía ⇧ izquierdo -shift_r se quedaba apagado-.

    Las dos derivan ahora de shortcuts.matched_keys(), así que se atan aquí
    de forma ESTRUCTURAL contra esa función, no contra un diccionario de
    teclas encendidas clavado a mano: para cada atajo de una sola tecla, si
    side_hint() dice "either side" tienen que estar encendidas las DOS
    teclas de matched_keys() y solo ellas; si dice "right"/"left" tiene que
    estar encendida esa única tecla. Sigue valiendo aunque mañana cambie
    cuál es la tecla de fábrica de cualquiera de los cuatro atajos.
    """
    lit = settings_window.lit_keys(ESTADO)
    for sid, fila in ESTADO.items():
        nombres = list(fila.get("keys") or [])
        if len(nombres) != 1:
            continue  # los combos no tienen lado; side_hint devuelve ""
        lado = shortcuts.side_hint(sid, nombres)
        casadas = shortcuts.matched_keys(sid, nombres)
        if lado == "either side":
            assert len(casadas) == 2, (sid, casadas)
        elif lado in ("right", "left"):
            assert len(casadas) == 1, (sid, casadas)
        else:
            continue
        for tecla in casadas:
            assert lit.get(tecla) == sid, (sid, tecla, lit)


def test_el_teclado_tiene_las_seis_filas_de_un_mac():
    assert len(settings_window.KEYBOARD_ROWS) == 6


def test_el_teclado_incluye_las_teclas_que_importan():
    todas = {n for fila in settings_window.KEYBOARD_ROWS for n, _ in fila if n}
    for n in ("esc", "cmd_r", "cmd", "shift", "ctrl", "alt", "m", "f13"):
        assert n in todas, n


def test_las_catorce_teclas_de_relleno_llevan_nombre_salvo_dos_huecos_reales():
    """Defecto 2 de la Task 9: KEYBOARD_ROWS dibujaba rectángulos en blanco
    para la puntuación y para ⇪/fn; en la captura de pantalla se leían como
    teclas rotas, no como "esto no se puede asignar". Ahora llevan nombre,
    aunque ninguna sea asignable, y por tanto su casilla nunca se enciende.

    Quedan exactamente dos casillas sin nombre A PROPÓSITO: un hueco de más
    en la fila de números (no hay tecla real ahí) y el bloque de flechas de
    la fila de abajo (son varias teclas, no una sola).
    """
    nombres = {n for fila in settings_window.KEYBOARD_ROWS for n, _ in fila if n}
    for n in ("-", "=", "[", "]", "\\", ";", "'", ",", ".", "/", "caps_lock", "fn"):
        assert n in nombres, n

    huecos = [n for fila in settings_window.KEYBOARD_ROWS for n, _ in fila if n == ""]
    assert len(huecos) == 2


def test_las_teclas_de_relleno_nombradas_llevan_la_leyenda_de_key_label():
    """Ata la casilla dibujada con key_label(), la misma función que ya
    pintan los keycaps de las cuatro filas: nada de una tabla paralela de
    símbolos en el sitio de dibujado (la instrucción explícita del brief).
    Estructural sobre TODOS los nombres de KEYBOARD_ROWS, no una lista de
    pares clavada a mano.
    """
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    nombres = {n for fila in settings_window.KEYBOARD_ROWS for n, _ in fila if n}
    for n in nombres:
        assert c._legends[n].stringValue() == settings_window.key_label([n]), n
        assert c._legends[n].stringValue() != "", n
    c.close()


def test_pintar_el_teclado_no_revienta():
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    c._paint_keyboard()
    assert len(c._keys) > 40
    c.close()


def _se_solapan(a, b):
    """Verdadero si dos NSRect comparten algún punto interior.

    Comparación geométrica genérica, no una fórmula atada a los números
    de esta ventana: sirve igual si mañana cambian PAD, ROW_H o la altura
    del teclado.
    """
    ax0, ay0 = a.origin.x, a.origin.y
    ax1, ay1 = ax0 + a.size.width, ay0 + a.size.height
    bx0, by0 = b.origin.x, b.origin.y
    bx1, by1 = bx0 + b.size.width, by0 + b.size.height
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def test_el_teclado_no_se_solapa_con_la_primera_fila():
    """El teclado se dibuja en la banda vacía de encima de las filas, no
    sobre ellas. Se compara la relación real entre los dos marcos —no se
    tocan, y el del teclado queda por encima— en vez de fijar un
    origin.y a mano: ese número quedaría obsoleto en cuanto la
    disposición se retocara legítimamente, y un test así pasaría aunque
    el teclado volviera a solaparse con cualquier otra fila.
    """
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    primer_sid = next(iter(shortcuts.SHORTCUTS))
    marco = c._teclado_marco.frame()
    fila = c._rows[primer_sid].frame()

    assert not _se_solapan(marco, fila), "el teclado invade la primera fila"
    # Coordenadas AppKit: origen abajo-izquierda. "Por encima" significa
    # que el borde inferior del teclado no cae por debajo del borde
    # superior de la fila.
    assert marco.origin.y >= fila.origin.y + fila.size.height

    c.close()


def test_las_casillas_con_nombre_tienen_su_leyenda():
    """El bug real de la Task 9: una casilla encendida sin leyenda no dice
    QUÉ tecla es — hay que contar posiciones en la fila para saberlo. Esto
    lee stringValue() de la leyenda ya renderizada, no solo que exista.

    El texto tiene que ser el mismo que produce key_label() para esa misma
    tecla sola: es la función que YA usan los keycaps de las cuatro filas
    (ver test_key_label_* en test_settings_window.py), y una segunda tabla
    de símbolos que tuviera que mantenerse de acuerdo con _SIMBOLO es
    precisamente la clase de bug que esta tarde se ha estado arreglando.
    """
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    esperado = {
        "esc": "esc", "f1": "F1", "f13": "F13",
        "cmd_r": "⌘", "cmd": "⌘", "shift": "⇧", "shift_r": "⇧",
        "ctrl": "⌃", "alt": "⌥", "alt_r": "⌥",
        "tab": "⇥", "enter": "⏎", "backspace": "⌫", "space": "␣",
        "m": "M", "a": "A", "1": "1", "0": "0",
    }
    for nombre, texto in esperado.items():
        assert c._legends[nombre].stringValue() == texto, nombre
        # la misma verdad que key_label(), no una tabla paralela
        assert c._legends[nombre].stringValue() == settings_window.key_label([nombre])
    c.close()


def test_toda_casilla_nombrada_tiene_exactamente_una_leyenda_y_las_de_relleno_ninguna():
    """Ni huérfanas (una casilla con nombre sin su leyenda) ni de más: las
    casillas de relleno ("") existen solo para que el teclado se reconozca
    de un vistazo y nunca se encienden (ver el comentario de KEYBOARD_ROWS),
    así que tampoco llevan leyenda."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    assert set(c._legends) == set(c._keys)
    assert len(c._legends) > 40
    c.close()


def test_repintar_el_teclado_no_reconstruye_las_leyendas():
    """_paint_keyboard() recolorea casillas existentes, nunca las
    reconstruye (ver el docstring de _build_keyboard: añadir y quitar
    subviews en cada repintado hace parpadear la ventana). Las leyendas
    tienen que seguir la misma regla: se crea el NSTextField una vez y se
    recolorea, no se crea uno nuevo con el mismo texto en cada repintado."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    antes = c._legends["cmd_r"]
    c._paint_keyboard()
    c._paint_keyboard()
    assert c._legends["cmd_r"] is antes
    c.close()


def test_la_leyenda_de_una_tecla_encendida_en_solido_cambia_de_color_para_seguir_siendo_legible():
    """dictation pinta su casilla de teal sólido (theme.TEAL): el gris
    oscuro de una leyenda apagada (theme.INK_KEYCAP) sería ilegible ahí.
    La leyenda tiene que recolorearse en el mismo sitio donde se recolorea
    el relleno (_paint_keyboard), o las dos se pueden desincronizar: una
    casilla encendida con su leyenda del color de una apagada.
    """
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    encendida = c._legends["cmd_r"]   # dictation en ESTADO: keys=["cmd_r"]
    apagada = c._legends["a"]         # ninguna asignación por defecto la toca

    assert apagada.textColor().isEqual_(theme.INK_KEYCAP)
    assert encendida.textColor().isEqual_(theme.PAGE_BG)
    assert not encendida.textColor().isEqual_(apagada.textColor())
    c.close()


def test_la_leyenda_de_una_tecla_encendida_en_tono_suave_sigue_legible():
    """cycle_mode/latch/cancel pintan su casilla de un teal muy claro
    (theme.MODEL_BTN_BG): ahí el gris oscuro de siempre ya es legible, así
    que la leyenda NO tiene que cambiar de color como en dictation — solo
    la casilla de relleno sólido necesita ese ajuste. Esto documenta la
    decisión con un test, no solo con un comentario."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    suave = c._legends["esc"]   # cancel en ESTADO: keys=["esc"]
    assert suave.textColor().isEqual_(theme.INK_KEYCAP)
    c.close()


def test_el_teclado_no_se_sale_del_contenido_de_la_ventana():
    """El error simétrico al solapamiento: un teclado desplazado de más
    hacia arriba se saldría del borde superior de la ventana en lugar de
    invadir las filas. Las dos pruebas juntas cubren los dos sentidos en
    los que un origen mal calculado puede fallar.
    """
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    marco = c._teclado_marco.frame()

    assert marco.origin.x >= 0
    assert marco.origin.y >= 0
    assert marco.origin.x + marco.size.width <= settings_window.W
    assert marco.origin.y + marco.size.height <= settings_window.H

    c.close()
