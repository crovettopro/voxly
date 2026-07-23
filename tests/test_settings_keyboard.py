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


def test_las_teclas_de_relleno_llevan_nombre_y_ya_no_quedan_huecos():
    """Defecto 2 de la Task 9 (primera ronda): KEYBOARD_ROWS dibujaba
    rectángulos en blanco para la puntuación y para ⇪/fn; en la captura de
    pantalla se leían como teclas rotas, no como "esto no se puede asignar".
    Ahora llevan nombre, aunque ninguna sea asignable, y por tanto su casilla
    nunca se enciende.

    Los dos huecos sin nombre que quedaban a propósito ya no existen
    (Defectos 3 y 4 de la segunda ronda): el de la fila de números era un
    error de retrato -un Mac ANSI de verdad empieza esa fila por el backtick
    y no tiene hueco entre "=" y ⌫-, y el bloque de flechas lleva ahora la
    leyenda "◀▼▶" con el nombre sintético "arrows". No queda ninguna casilla
    sin nombre.
    """
    nombres = {n for fila in settings_window.KEYBOARD_ROWS for n, _ in fila if n}
    for n in ("`", "-", "=", "[", "]", "\\", ";", "'", ",", ".", "/",
              "caps_lock", "fn", "arrows"):
        assert n in nombres, n

    huecos = [n for fila in settings_window.KEYBOARD_ROWS for n, _ in fila if n == ""]
    assert huecos == []


def test_keyboard_rows_sin_teclas_huerfanas_devuelve_el_retrato_tal_cual():
    """Sin ninguna tecla asignada fuera de KEYBOARD_ROWS, keyboard_rows() no
    inventa una fila extra: devuelve KEYBOARD_ROWS tal cual, para que la
    geometría (alto_fila) no cambie sin que nada lo justifique."""
    assert settings_window.keyboard_rows(ESTADO) == settings_window.KEYBOARD_ROWS


def test_toda_tecla_de_lit_keys_aparece_en_el_layout_dibujado():
    """Defecto 1 de la Task 9 (segunda ronda): KEYBOARD_ROWS retrata un
    MacBook y no contiene toda tecla asignable -f14 es el ejemplo: la app la
    acepta por config.yaml/prefs.json (keys._FUNCIONES) aunque el retrato
    solo pinte f1..f13-. Con la tecla encendida en la lista y ausente del
    teclado, el usuario ve exactamente la contradicción que este componente
    existe para impedir.

    Estructural y no una lista de casos: para varios estados -uno con una
    tecla claramente fuera del retrato (f14) y otro con dos huérfanas a la
    vez (f14 y f15)- toda clave de lit_keys() tiene que aparecer entre los
    nombres de keyboard_rows(). Nada de comparar la fila extra contra una
    lista clavada a mano.
    """
    estados = [
        ESTADO,
        dict(ESTADO, dictation={"keys": ["f14"], "style": "hold", "delay_ms": 0}),
        dict(ESTADO, latch={"keys": ["f15"]}),
        dict(ESTADO,
             dictation={"keys": ["f14"], "style": "hold", "delay_ms": 0},
             latch={"keys": ["f15"]}),
    ]
    for estado in estados:
        filas = settings_window.keyboard_rows(estado)
        nombres = {n for fila in filas for n, _ in fila if n}
        for tecla in settings_window.lit_keys(estado):
            assert tecla in nombres, (estado, tecla)


def test_una_tecla_fuera_del_retrato_se_ve_de_verdad_en_la_ventana():
    """No basta con que keyboard_rows() incluya la tecla huérfana en teoría:
    _build_keyboard() tiene que usar esa fila de verdad para que la casilla
    exista en la ventana real, con su leyenda, o la ventana seguiría
    mostrando la misma contradicción que este defecto arregla."""
    estado = dict(ESTADO, dictation={"keys": ["f14"], "style": "hold", "delay_ms": 0})
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        estado, lambda sid, fila: (True, ""))
    assert "f14" in c._keys
    assert c._legends["f14"].stringValue() == settings_window.key_label(["f14"])
    assert settings_window.lit_keys(estado)["f14"] == "dictation"
    c.close()


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


def test_la_casilla_huerfana_tiene_ancho_de_modificadora_no_de_fila():
    """Defecto 1 de la Task 9 (tercera ronda): con una sola tecla huérfana en
    la fila, un peso proporcional de 1.0 se llevaba el 100% del ancho y la
    casilla se dibujaba como una barra espaciadora -justo lo que un teclado
    dibujado existe para no mentir. La casilla huérfana tiene que salir con
    un ancho comparable al de una tecla modificadora normal del retrato
    (aquí "cmd"), muy por debajo del ancho completo de la fila. Comparación
    estructural entre anchos ya dibujados, nada de una constante de píxeles
    clavada.
    """
    estado = dict(ESTADO, dictation={"keys": ["f14"], "style": "hold", "delay_ms": 0})
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        estado, lambda sid, fila: (True, ""))

    ancho_huerfana = c._keys["f14"].frame().size.width
    ancho_cmd = c._keys["cmd"].frame().size.width
    ancho_fila = c._teclado_marco.frame().size.width

    # "Comparable", no idéntico a fuerza: unos pocos puntos de margen
    # absorben el redondeo de la aritmética de pesos sin dejar pasar una
    # regresión al reparto proporcional de antes.
    assert abs(ancho_huerfana - ancho_cmd) < 2.0, (ancho_huerfana, ancho_cmd)
    assert ancho_huerfana < ancho_fila / 3, (ancho_huerfana, ancho_fila)
    c.close()


def test_la_casilla_huerfana_no_se_estira_con_varias_huerfanas_a_la_vez():
    """La misma garantía que el test anterior, pero con dos teclas huérfanas
    en la fila a la vez (f15 y f14): cada una sigue con el ancho de una
    modificadora normal, no el de la fila repartido entre dos.
    """
    estado = dict(ESTADO,
                   dictation={"keys": ["f15"], "style": "hold", "delay_ms": 0},
                   latch={"keys": ["f14"]})
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        estado, lambda sid, fila: (True, ""))

    ancho_cmd = c._keys["cmd"].frame().size.width
    for tecla in ("f15", "f14"):
        ancho = c._keys[tecla].frame().size.width
        assert abs(ancho - ancho_cmd) < 2.0, (tecla, ancho, ancho_cmd)
    c.close()


def test_el_resto_de_la_fila_huerfana_no_dibuja_ninguna_casilla():
    """Defecto 1 de la Task 9 (tercera ronda): el ancho que la casilla
    huérfana no usa se queda vacío -fondo del teclado, sin vista dibujada-
    en vez de una casilla de relleno apagada, que es justo el "agujero sin
    leyenda que parece tecla rota" de la ronda anterior. keyboard_rows()
    reserva ese resto con un nombre `None`; este test comprueba que
    _build_keyboard() de verdad lo salta y no crea ninguna casilla ni
    leyenda para él.
    """
    estado = dict(ESTADO, dictation={"keys": ["f14"], "style": "hold", "delay_ms": 0})
    fila_huerfana = settings_window.keyboard_rows(estado)[-1]
    huecos = [n for n, _ in fila_huerfana if n is None]
    assert huecos, "la fila huérfana debería reservar hueco vacío"

    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        estado, lambda sid, fila: (True, ""))
    # Ninguna casilla ni leyenda lleva clave None: no hay vista para el hueco.
    assert None not in c._keys
    assert None not in c._legends
    c.close()


def test_la_fila_huerfana_explica_por_que_esa_tecla_esta_ahi():
    """Defecto 2 de la Task 9 (tercera ronda): una tecla huérfana suelta y
    sin explicación parece puesta al azar. La ventana tiene que mostrar el
    texto "not on this keyboard" cuando hay fila huérfana, y NO mostrarlo
    cuando no la hay (el caso común, con el estado de fábrica).
    """
    sin_huerfanas = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    assert sin_huerfanas._nota_huerfana is None
    sin_huerfanas.close()

    estado = dict(ESTADO, dictation={"keys": ["f14"], "style": "hold", "delay_ms": 0})
    con_huerfana = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        estado, lambda sid, fila: (True, ""))
    assert con_huerfana._nota_huerfana is not None
    assert con_huerfana._nota_huerfana.stringValue() == settings_window.NOTA_HUERFANA
    con_huerfana.close()


def test_el_texto_de_la_fila_huerfana_no_se_recorta():
    """La Task 8 recortó "either side" en silencio con un campo de ancho
    clavado a ojo, y el test que leía stringValue() pasaba igual porque
    stringValue() no sabe nada del glifo cortado. Aquí se comprueba lo
    mismo que evitó ese bug: el campo dibujado mide, medido con la MISMA
    función (theme.text_width) que _build_keyboard() usa para dimensionarlo,
    al menos tanto como el texto necesita con su propia fuente -si el campo
    fuera más angosto, el texto (correcto en stringValue()) se recortaría al
    dibujarse sin que este test lo notara igual que le pasó a la Task 8.
    """
    estado = dict(ESTADO, dictation={"keys": ["f14"], "style": "hold", "delay_ms": 0})
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        estado, lambda sid, fila: (True, ""))
    nota = c._nota_huerfana
    ancho_necesario = theme.text_width(nota.stringValue(), nota.font())
    assert nota.frame().size.width >= ancho_necesario
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


# --- captura: verde = usable, gris = no usable (feedback de POMI) ---

def _controller(estado=None):
    return settings_window.ShortcutsController.alloc().initWithState_onChange_(
        estado or ESTADO, lambda sid, fila: (True, ""))


def test_durante_la_captura_las_letras_se_apagan_y_las_usables_se_encienden():
    """Capturando Dictation: una letra inutilizaría el teclado entero
    (validate la rechaza) → gris; una F o un modificador con lado → teal
    SÓLIDO con leyenda en papel. El teal claro de la primera versión
    (MODEL_BTN_BG) no se distinguía del gris en pantalla — "el teclado se ve
    completo", dijo Eduardo — así que el contraste es parte del contrato.
    La verdad la pone shortcuts.validate, el MISMO validador que luego acepta
    o rechaza la captura — el color no puede prometer lo que validate negará."""
    c = _controller()
    c.begin_capture_("dictation")

    assert c._legends["a"].textColor().isEqual_(theme.INK_MUTED)     # letra: no
    assert c._legends["esc"].textColor().isEqual_(theme.INK_MUTED)   # dueña de cancel
    assert c._legends["shift"].textColor().isEqual_(theme.INK_MUTED) # dueña de latch
    assert c._legends["f13"].textColor().isEqual_(theme.PAGE_BG)     # usable: encendida
    assert c._legends["cmd_r"].textColor().isEqual_(theme.PAGE_BG)   # la suya: usable
    c.close()


def test_las_decorativas_nunca_se_encienden_en_captura():
    """⇪ y el bloque de flechas tienen leyenda pero no son asignables: en
    captura salen en gris, no como promesa de tecla elegible. fn ya NO está
    aquí: desde que hotkey.py la endereza es una tecla de dictado de pleno
    derecho (ver el test siguiente)."""
    c = _controller()
    c.begin_capture_("dictation")
    for nombre in ("caps_lock", "arrows", ";", ","):
        assert c._legends[nombre].textColor().isEqual_(theme.INK_MUTED), nombre
    c.close()


def test_fn_se_enciende_capturando_dictation():
    """La tecla estrella de Wispr Flow, pedida expresamente ("es vital tener
    también fn"): capturando Dictation tiene que ofrecerse en verde."""
    c = _controller()
    c.begin_capture_("dictation")
    assert c._legends["fn"].textColor().isEqual_(theme.PAGE_BG)
    c.close()


def test_los_modificadores_izquierdos_se_encienden_capturando_dictation():
    """El ⌘/⌥/⌃ izquierdos son teclas de dictado legítimas (DICTATION_KEYS
    las ofrece, con guarda): el teclado tiene que ofrecerlas en verde, no
    dejarlas grises como si no existiera forma de elegirlas. shift no: sigue
    reservada para latch."""
    c = _controller()
    c.begin_capture_("dictation")
    for nombre in ("cmd", "alt", "ctrl"):
        assert c._legends[nombre].textColor().isEqual_(theme.PAGE_BG), nombre
    assert c._legends["shift"].textColor().isEqual_(theme.INK_MUTED)
    c.close()


def test_cada_atajo_tiene_sus_propias_usables():
    """esc es gris capturando Dictation (pertenece a Cancel) pero verde
    capturando Cancel (confirmar tu propia tecla nunca es conflicto)."""
    c = _controller()
    c.begin_capture_("cancel")
    assert c._legends["esc"].textColor().isEqual_(theme.PAGE_BG)
    assert c._legends["cmd_r"].textColor().isEqual_(theme.INK_MUTED)  # de Dictation
    c.close()


def test_al_salir_de_la_captura_vuelve_el_pintado_por_asignaciones():
    c = _controller()
    c.begin_capture_("dictation")
    c.cancel_capture_()
    # dictation vuelve a su teal sólido (leyenda en color papel) y la letra
    # suelta recupera el gris oscuro normal de una tecla apagada.
    assert c._legends["cmd_r"].textColor().isEqual_(theme.PAGE_BG)
    assert c._legends["a"].textColor().isEqual_(theme.INK_KEYCAP)
    c.close()


def test_aplicar_una_captura_valida_tambien_restaura_el_teclado():
    c = _controller()
    c.begin_capture_("dictation")
    c.apply_capture_(["f13"])
    assert c._capturing is None
    # f13 es ahora la tecla de dictado: teal sólido con leyenda en papel.
    assert c._legends["f13"].textColor().isEqual_(theme.PAGE_BG)
    assert c._legends["a"].textColor().isEqual_(theme.INK_KEYCAP)
    c.close()
