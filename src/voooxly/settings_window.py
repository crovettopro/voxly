"""Ventana de Shortcuts: reasignar los cuatro atajos capturando teclas.

NSWindow, NUNCA NSPanel: en macOS 26 (Darwin 25) el window server no compone
un NSPanel — isVisible devuelve True y no hay un solo píxel. El HUD estuvo
roto en silencio por eso durante semanas. Verificar SIEMPRE con screencapture.

NSWindow solo se puede instanciar en el hilo principal, igual que overlay.py y
onboarding.py. La captura llega por el hilo del listener de pynput, así que
todo repintado que salga de ella va por AppHelper.callAfter.

Este módulo solo pinta y recoge: quién puede tener qué tecla lo decide
shortcuts.py, que es puro y está probado.
"""
from __future__ import annotations

import logging
import math

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSButton,
    NSSlider,
    NSTextAlignmentCenter,
    NSTextAlignmentRight,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRect, NSObject

from . import keys, shortcuts, theme

log = logging.getLogger("voooxly.settings_window")

W, H = 560, 620
PAD = 28
ROW_H = 46

# Nombre pynput → símbolo de macOS. Lo que el usuario ve en un teclado.
_SIMBOLO = {
    "cmd": "⌘", "cmd_l": "⌘", "cmd_r": "⌘",
    "alt": "⌥", "alt_l": "⌥", "alt_r": "⌥", "alt_gr": "⌥",
    "ctrl": "⌃", "ctrl_l": "⌃", "ctrl_r": "⌃",
    "shift": "⇧", "shift_l": "⇧", "shift_r": "⇧",
    "space": "␣", "enter": "⏎", "tab": "⇥", "backspace": "⌫",
    "caps_lock": "⇪",
    # "arrows" no es un nombre de tecla pynput (keys.validate_custom lo
    # rechaza): es el nombre sintético de la casilla de relleno que
    # representa el bloque de flechas del teclado visual (Task 9, Defecto
    # 4 — un rectángulo vacío ahí se leía como tecla rota). Vive en esta
    # tabla y no como caso especial en _build_keyboard() por la misma
    # razón que ⇪ y fn: una segunda tabla de símbolos en el sitio de
    # dibujado es justo el bug que este módulo lleva evitando toda la tarde.
    "arrows": "◀▼▶",
}

def y_(top, h):
    """'y desde arriba' (como en el diseño) → origen abajo-izquierda."""
    return H - top - h


def key_label(names: list[str]) -> str:
    """['ctrl','shift','m'] → '⌃⇧M'. Lo que se pinta en el keycap.

    También es la única tabla de símbolos del módulo: las casillas de
    relleno del teclado visual (Task 9, Defecto 2 — ⇪ y fn no tienen tecla
    asignable pero sí necesitan leyenda) pasan por aquí igual que los
    keycaps de las cuatro filas, para que no exista una segunda tabla
    paralela que se pueda desincronizar de esta.
    """
    fuera = []
    for n in names or []:
        low = n.lower()
        if low in _SIMBOLO:
            fuera.append(_SIMBOLO[low])
        elif low in ("esc", "fn"):
            fuera.append(low)
        else:
            fuera.append(low.upper())
    return "".join(fuera)


# Los cuatro valores que shortcuts.side_hint puede devolver (ver su
# docstring): la etiqueta de lado se dimensiona sobre el más ancho de
# estos con AppKit, no sobre un número puesto a ojo. Ese fue justo el bug:
# 58pt alcanzaban para "right" pero "either side" ya no cabía, y el texto
# (correcto) se recortaba en pantalla sin que ningún test lo viera, porque
# stringValue() sigue devolviendo el texto completo aunque el glifo se
# corte al dibujarse.
_LADOS_POSIBLES = ("right", "left", "either side", "")
_LADO_HOLGURA = 6   # aire entre el texto medido y el borde del campo
_LADO_ALTO = 15
_LADO_GAP = 4       # hueco entre el campo de chips y la etiqueta de lado
_LADO_MARGEN_D = 4  # hueco entre el campo y el borde de la fila

# Campo de chips estilo Wispr Flow (feedback de Eduardo, con capturas):
# cada tecla del atajo es su PROPIO chip (⌃ ⇧ M, tres chips) dentro de un
# campo blanco con un lápiz ✎ al final. El lápiz ES la afordancia de editar
# — "Change" como texto suelto no se identificaba como acción. El click de
# verdad lo sigue recibiendo el botón invisible de toda la fila.
_CHIP_FONT_PT = 12.5
_CHIP_PESO = 0.3
_CHIP_H = 22
_CHIP_PAD = 7        # aire horizontal dentro de cada chip
_CHIP_GAP = 4        # hueco entre chips
_FIELD_PAD = 8       # aire interior del campo, a ambos lados
_FIELD_H = 32
_PENCIL_TXT = "✎"
_PENCIL_W = 16
_FIELD_MIN_W = 110
# Placeholder del campo durante la captura, hasta que cae la primera tecla
# (el análogo del "Click to add a shortcut" de Wispr). Cabe de sobra: el
# campo mide _FIELD_MIN_W como poco y la frase ~62pt a 11pt.
_FIELD_HINT = "Press keys…"

# El "Reset to default" de Wispr (sale en las tres capturas del feedback):
# vuelve los cuatro atajos a fábrica en un click.
_RESET_TXT = "Reset to defaults"


def chip_texts(names: list[str]) -> list[str]:
    """['ctrl','shift','m'] → ['⌃','⇧','M']: un chip por tecla, estilo Wispr.

    Pasa por key_label tecla a tecla para que el chip y la leyenda del
    teclado visual no puedan escribir la misma tecla de dos formas."""
    return [key_label([n]) for n in (names or [])]


def _chip_ancho(texto: str, font) -> float:
    """Ancho de un chip: su texto medido de verdad (theme.text_width, la
    lección de _lado_ancho) con aire a ambos lados, y nunca más estrecho que
    alto — un chip de una letra se dibuja cuadrado, no como una astilla."""
    return max(math.ceil(theme.text_width(texto, font)) + 2 * _CHIP_PAD, _CHIP_H)


def _chips_ancho(textos: list[str], font) -> float:
    if not textos:
        return 0.0
    return sum(_chip_ancho(t, font) for t in textos) + _CHIP_GAP * (len(textos) - 1)


def field_width(estado: dict, font) -> float:
    """Ancho ÚNICO del campo de chips, compartido por las cuatro filas (la
    misma decisión que lado_w): el máximo que pide cualquier binding actual
    más el lápiz, con _FIELD_MIN_W de suelo. Compartirlo deja la columna
    alineada — cuatro campos de anchos distintos se leerían escalonados."""
    necesita = max(
        (_chips_ancho(chip_texts(list((fila or {}).get("keys") or [])), font)
         for fila in estado.values()),
        default=0.0,
    )
    return max(_FIELD_MIN_W, necesita + 2 * _FIELD_PAD + _PENCIL_W + _CHIP_GAP)

# Alto extra que gana la fila de Dictation para el slíder de delay (ver
# _build_row): el contenido de siempre (título, subtítulo, keycap, lado) se
# desplaza este mismo alto hacia arriba, así que ocupa exactamente el mismo
# rectángulo que ocuparía en una fila normal de ROW_H, y el slíder vive en la
# banda nueva que queda libre debajo, DENTRO del frame de la fila -no fuera
# de él-, para que no invada la fila de abajo (ver el comentario largo en
# _build_row).
#
# Subido de 24 a 36 en el Finding 1 del review: con 24 el slíder (alto 20)
# llegaba pegado al borde inferior de la fila y no quedaba sitio para las
# marcas nuevas debajo de la pista. Los 12pt de más son exactamente los que
# piden _DELAY_MARCA_H + el hueco que las separa del slíder (ver más abajo);
# subir esta constante empuja automáticamente todas las filas siguientes
# (Cycle mode incluida) hacia abajo -_build() sólo repite alto_fila+1-, así
# que no hace falta tocar nada más para que no se coman una a otra.
_DELAY_ROW_EXTRA_H = 36

# Geometría del slíder y sus marcas dentro de la banda [0, _DELAY_ROW_EXTRA_H)
# que queda libre debajo del contenido normal de la fila de Dictation (ver el
# comentario de arriba y el de _build_row). El slíder sube de su antiguo y=2
# a _DELAY_SLIDER_Y=14 para dejar, debajo, la franja [0, 14) para las marcas
# -antes esa franja no existía y las marcas no tenían dónde ir sin invadir
# nada-, conservando el mismo margen de ~8pt entre el slíder y el subtítulo
# de arriba que ya tenía el diseño original.
_DELAY_SLIDER_Y = 14
_DELAY_MARCA_Y = 0
_DELAY_MARCA_H = 11
_DELAY_MARCA_PT = 9.0        # pequeñas y en gris secundario, como pide el brief
# 2pt de holgura recortaba en pantalla el último dígito de "200"/"400"/"600"
# (comprobado con screencapture: "200" se leía "20"), aunque
# theme.text_width() midiera "bien" -sizeWithAttributes_ da el avance puro
# del glifo, no el hueco que la celda de un NSTextField quiere alrededor.
# 6pt es la misma holgura que ya usan _LADO_HOLGURA y _NOTA_HUERFANA_HOLGURA
# más arriba en este módulo, y ahí no recorta.
_DELAY_MARCA_HOLGURA = 6.0   # aire entre el texto medido de cada marca y su campo
_DELAY_VALOR_PT = 13.5
_DELAY_VALOR_PESO = 0.5      # negrita de verdad (NSFontWeightBold es 0.40)
_DELAY_VALOR_GAP = 14.0      # hueco entre el borde derecho del slíder y el valor
_DELAY_VALOR_HOLGURA = 6.0   # aire entre el texto medido del valor y su campo


def _marcas_delay() -> list[int]:
    """Los cinco valores que reparte el slíder de delay (Finding 1 del
    review): 0, MAX/4, MAX/2, 3·MAX/4 y MAX -no 0/200/400/600/800 clavados a
    mano-, para que si mañana cambia shortcuts.MAX_DELAY_MS las marcas lo
    sigan solas, sin que haga falta acordarse de tocar este número también
    aquí (la misma lección que _lado_ancho() ya aplica con
    shortcuts.side_hint más arriba en este módulo)."""
    paso = shortcuts.MAX_DELAY_MS / 4
    return [round(paso * i) for i in range(5)]


def _fmt_delay(ms) -> str:
    """'400 ms': el formato exacto que pide el brief para el valor elegido."""
    return f"{int(ms)} ms"


def _valor_ancho(font) -> float:
    """Ancho que necesita el texto del valor del delay ('N ms') para
    CUALQUIER N entre 0 y shortcuts.MAX_DELAY_MS, medido de verdad con
    AppKit sobre el rango entero: un font proporcional no mide lo mismo
    para todas las cifras de tres dígitos, así que el peor caso se calcula
    sobre el rango completo en vez de asumir que el valor máximo es el más
    ancho (la misma razón por la que _lado_ancho() mide las cuatro
    posibilidades de side_hint en vez de clavar un número)."""
    return math.ceil(max(
        theme.text_width(_fmt_delay(ms), font)
        for ms in range(0, shortcuts.MAX_DELAY_MS + 1)
    )) + _DELAY_VALOR_HOLGURA


def _alto_multilinea(font, lineas=2) -> float:
    """Alto en puntos que necesitan `lineas` líneas de `font`, medido con las
    métricas reales de AppKit (ascender/descender/leading) en vez de doblar
    a ojo el alto de una línea: el mismo principio que theme.text_width()
    ya aplica al ancho, aplicado ahora al alto (Finding 3 del review: el
    campo de error vivía al filo con una sola línea fija de 17pt)."""
    alto_linea = math.ceil(font.ascender() - font.descender() + font.leading())
    return alto_linea * lineas

# Tamaño de la leyenda de cada casilla del teclado visual. 9pt le sobra hueco
# incluso al texto más ancho ("F13") en la casilla más estrecha del teclado
# (~30pt de ancho real, medido con theme.text_width): no hace falta ganar
# tamaño de ventana para que se lea.
_LEYENDA_TECLADO_PT = 9.0

# Texto de la fila huérfana (Task 9, tercera ronda, Defecto 2): sin él, una
# tecla suelta al final del teclado parece puesta al azar. En inglés, como
# el resto de la interfaz.
NOTA_HUERFANA = "not on this keyboard"
_NOTA_HUERFANA_PT = 10.0
_NOTA_HUERFANA_HOLGURA = 6.0   # aire entre el texto medido y su campo
_NOTA_HUERFANA_MARGEN_D = 8.0  # aire entre el texto y el borde derecho del teclado


def _nota_huerfana_ancho(font) -> float:
    """Puntos que necesita el texto de la fila huérfana con `font`, medidos
    de verdad con AppKit (theme.text_width) en vez de clavados a ojo: la
    misma lección que _lado_ancho() ya aplica más abajo -en la Task 8 un
    campo de 58pt recortó "either side" en silencio y el test que leía
    stringValue() pasaba igual."""
    return math.ceil(theme.text_width(NOTA_HUERFANA, font)) + _NOTA_HUERFANA_HOLGURA


def _lado_ancho(font) -> float:
    """Puntos que necesita el campo del lado para no cortar ningún valor de
    shortcuts.side_hint con `font`, medido de verdad con AppKit.

    Autodefensivo a propósito: si mañana side_hint gana un quinto valor más
    largo que "either side", basta con añadirlo a _LADOS_POSIBLES — el
    ancho se recalcula solo, no hay un número de puntos que reajustar
    también a mano y que se pueda olvidar.
    """
    return math.ceil(max(theme.text_width(t, font) for t in _LADOS_POSIBLES)) + _LADO_HOLGURA


def side_label(sid: str, names: list[str]) -> str:
    """'right' / 'left' / 'either side' / '' — el matiz que un símbolo ⌘ solo
    no puede dar.

    Envoltorio de presentación: la decisión de qué lado(s) casan de verdad en
    runtime es semántica de atajos, no de pintado, y vive en
    shortcuts.side_hint (probada ahí sin AppKit). Hace falta `sid` y no solo
    el nombre de la tecla porque el mismo nombre significa cosas distintas
    según el atajo — "shift" en latch casa las dos manos (hotkey.py:421),
    pero un combo o una tecla sin lado en cualquier otro atajo no la casan.
    """
    return shortcuts.side_hint(sid, names)


# Teclado de un MacBook, por filas. (nombre pynput, nombre sintético de
# relleno como "arrows", o "" si hiciera falta una casilla puramente muda; hoy
# ninguna fila la usa, ver más abajo), ancho relativo). Las teclas asignadas
# que este retrato no contenga las añade keyboard_rows() en una fila aparte:
# _build_keyboard() nunca dibuja KEYBOARD_ROWS directamente, dibuja lo que
# esa función devuelve.
#
# Las letras y dígitos se nombran (con el char en minúscula que reporta
# hotkey._norm) y no solo "m": shortcuts.py no restringe qué tecla puede
# entrar en un combo de varias teclas (solo valida la tecla suelta), así que
# cycle_mode se puede reasignar a cualquier ctrl+alt+<letra> — si el teclado
# solo supiera encender "m", esa reasignación se vería en la fila pero nunca
# en el dibujo, rompiendo la regla de que las dos vistas son la misma verdad.
#
# La puntuación (`, -, =, [, ], \, ;, ', ,, ., /) y las dos teclas especiales
# de la fila de abajo (⇪ caps lock, fn) SÍ se nombran, aunque ninguna sea
# asignable hoy (Task 9, Defecto 2): sin nombre se pintaban como rectángulos
# en blanco y en la captura de pantalla se leían como teclas rotas, no como
# "esto no se puede asignar". Nombrarlas les da leyenda vía key_label() sin
# encenderlas nunca (lit_keys() nunca las incluye porque ningún atajo puede
# apuntar a ellas — ver keys.validate_custom). El bloque de flechas del final
# de la fila de abajo lleva el nombre sintético "arrows" por el mismo motivo
# (Task 9 fix2, Defecto 4): son varias teclas y no una sola, así que no
# puede ser asignable, pero un rectángulo sin leyenda ahí se lee igual de
# roto que los demás. No queda ninguna casilla sin nombre: el hueco que
# tenía la fila de números (Defecto 3) era un error de retrato -en un Mac
# ANSI de verdad esa fila empieza por el backtick y no tiene hueco entre
# "=" y ⌫-, no una casilla de relleno legítima.
KEYBOARD_ROWS: list[list[tuple[str, float]]] = [
    [("esc", 1.4)] + [(f"f{i}", 1.0) for i in range(1, 13)] + [("f13", 1.0)],
    [("`", 1.0)] + [(d, 1.0) for d in "1234567890"] + [("-", 1.0), ("=", 1.0)] + [("backspace", 1.5)],
    [("tab", 1.5)] + [(c, 1.0) for c in "qwertyuiop"] + [("[", 1.0), ("]", 1.0)] + [("\\", 1.2)],
    [("caps_lock", 1.7)] + [(c, 1.0) for c in "asdfghjkl"] + [(";", 1.0), ("'", 1.0)] + [("enter", 1.6)],
    [("shift", 2.2)] + [(c, 1.0) for c in "zxcvbnm"] + [(",", 1.0), (".", 1.0), ("/", 1.0)] + [("shift_r", 2.2)],
    # La fila de abajo lleva los cuatro modificadores en AMBOS lados para que
    # izquierda y derecha sean simétricas: antes faltaba ctrl_r y quien la
    # asignaba la veía caer en la fila "not on this keyboard", mientras que
    # cmd_r y alt_r sí tenían casilla. El peso se lo recortamos a la barra
    # espaciadora (5.6 → 4.5) para que el total de la fila no cambie.
    [("fn", 1.1), ("ctrl", 1.1), ("alt", 1.1), ("cmd", 1.4), ("space", 4.5),
     ("cmd_r", 1.4), ("alt_r", 1.1), ("ctrl_r", 1.1), ("arrows", 2.2)],
]

# Quién gana cuando dos atajos comparten una tecla física. Dictation primero:
# es la que el usuario busca de un vistazo, y sin una regla explícita el color
# dependería del orden de iteración del diccionario.
_PRIORIDAD = ("dictation", "cancel", "latch", "cycle_mode")


def delay_for(names: list[str], anterior_ms: int) -> int:
    """Delay que le toca a una tecla recién capturada.

    Sube al default SOLO si la tecla necesita guarda y el delay actual no la
    protege: con el ⌘ izquierdo a 0 ms, cada ⌘C arranca una grabación. Si la
    tecla no necesita guarda se conserva lo que hubiera — subir a 400 a quien
    eligió el ⌘ derecho le cambiaría el tacto de la app sin pedirlo, y bajarle
    un 600 puesto a mano le pisaría su elección.
    """
    if names and keys.needs_guard(names[0]) and anterior_ms <= 0:
        return shortcuts.DEFAULT_DELAY_MS
    return anterior_ms


def lit_keys(estado: dict) -> dict[str, str]:
    """{nombre canónico: sid} de las teclas que hay que encender.

    Deriva de shortcuts.matched_keys(), no de canonicalizar cada nombre a
    mano: matched_keys() sabe que latch ensancha a la variante derecha
    (hotkey.py:421 casa por prefijo) y side_label() cuenta exactamente la
    misma historia (shortcuts.side_hint() usa la misma función). Antes de
    este fix las dos vistas se calculaban por separado y se desincronizaban
    -el bug real de la Task 9: "shift" encendido, "shift_r" apagado, la fila
    diciendo "either side".
    """
    fuera: dict[str, str] = {}
    for sid in _PRIORIDAD:
        nombres = list((estado.get(sid, {}) or {}).get("keys") or [])
        if not nombres:
            continue
        for canon in shortcuts.matched_keys(sid, nombres):
            if canon not in fuera:
                fuera[canon] = sid
    return fuera


# Referencia de "tecla modificadora normal" para el ancho de una casilla
# huérfana (Task 9, tercera ronda, Defecto 1): la fila de abajo del retrato
# es la que tiene más modificadoras juntas, y "cmd" es justo el ejemplo que
# pide el brief. Se leen de KEYBOARD_ROWS en vez de clavarse a mano para que
# si mañana cambia el peso de "cmd" en el retrato, la huérfana lo siga sin
# que haga falta acordarse de tocar dos sitios.
_FILA_MODIFICADORAS = KEYBOARD_ROWS[-1]
_PESO_MODIFICADOR = next(w for n, w in _FILA_MODIFICADORAS if n == "cmd")
_PESO_FILA_MODIFICADORAS = sum(w for _, w in _FILA_MODIFICADORAS)


def keyboard_rows(estado: dict) -> list[list[tuple[str | None, float]]]:
    """KEYBOARD_ROWS y, si hace falta, una fila extra con las teclas
    asignadas que ese retrato de MacBook no dibuja.

    Defecto 1 de la Task 9 (segunda ronda): KEYBOARD_ROWS retrata un MacBook
    concreto, pero hay teclas asignables que ese retrato no contiene -ctrl_r
    es la primera, keys.DICTATION_KEYS:114 ya la ofrece en el menú hoy y un
    prefs.json real puede traerla tras shortcuts.migrate()-. Sin esta fila
    extra la lista decía "⌃ right" y el teclado no encendía nada: exactamente
    la contradicción que este componente existe para impedir.

    Se construye sobre lit_keys(), no sobre una lista de nombres puesta a
    mano, para que CUALQUIER tecla asignable futura caiga aquí sola -f14, una
    tecla del teclado numérico, home...- en cuanto algún atajo la use de
    verdad, sin que haga falta acordarse de tocar este módulo otra vez.

    Sin huérfanas devuelve KEYBOARD_ROWS tal cual (ni una fila de más ni una
    lista distinta que comparar), así que la geometría de siempre no cambia
    para el caso común.

    Defecto 1 de la tercera ronda: cada huérfana lleva el mismo peso que
    "cmd" en la fila de abajo (_PESO_MODIFICADOR), no un peso de 1.0 que solo
    significa algo comparado con las demás casillas de ESA fila -con una sola
    casilla en la fila, peso 1.0 es el 100% del ancho y la casilla se dibuja
    como una barra espaciadora, el defecto que este arreglo corrige. El resto
    del peso de referencia (_PESO_FILA_MODIFICADORAS) se reserva con un
    nombre `None`: una casilla que _build_keyboard() cuenta para el ancho
    pero nunca dibuja, así que el resto de la fila queda vacío -fondo, sin
    casilla- en vez de un hueco sin leyenda que parece tecla rota.
    """
    en_retrato = {n for fila in KEYBOARD_ROWS for n, _ in fila if n}
    huerfanas = sorted(n for n in lit_keys(estado) if n not in en_retrato)
    if not huerfanas:
        return KEYBOARD_ROWS
    fila_huerfana: list[tuple[str | None, float]] = [
        (n, _PESO_MODIFICADOR) for n in huerfanas]
    resto = _PESO_FILA_MODIFICADORAS - _PESO_MODIFICADOR * len(huerfanas)
    if resto > 0:
        fila_huerfana.append((None, resto))
    return [*KEYBOARD_ROWS, fila_huerfana]


def _apagar(casilla):
    """Deja una casilla del teclado en su color base (sin asignar).

    Función de módulo, no método: un nombre con un solo guion bajo inicial y
    ninguno más ("_apagar") es, para el transformador de selectores de
    PyObjC, indistinguible de un selector Objective-C de CERO argumentos
    (`default_selector` solo trata el método como Python puro cuando lleva
    OTRO guion bajo además del inicial, o termina en uno). Como método de
    ShortcutsController con un argumento (`casilla`) revienta al definir la
    clase con `objc.BadPrototypeError: '_apagar' expects 0 arguments`. Fuera
    de la clase no hay transformación de selector que lo confunda.
    """
    casilla.layer().setBackgroundColor_(theme.KEYCAP_BG2.CGColor())
    casilla.layer().setBorderWidth_(1.0)
    casilla.layer().setBorderColor_(theme.HAIRLINE.CGColor())


class ShortcutsController(NSObject):
    """Controlador + ventana. Subclase de NSObject para ser target de los
    botones y delegate de la ventana."""

    def initWithState_onChange_(self, estado, on_change):
        self = objc.super(ShortcutsController, self).init()
        if self is None:
            return None
        self._estado = {sid: dict(fila) for sid, fila in estado.items()}
        self._on_change = on_change
        self._rows = {}          # sid → NSView de la fila
        self._fields = {}        # sid → NSView del campo de chips (estilo Wispr)
        self._chips = {}         # sid → [NSView]: un chip por tecla del binding
        self._pencils = {}       # sid → NSTextField del lápiz ✎ del campo
        self._hints = {}         # sid → NSTextField placeholder ("Press keys…")
        self._sides = {}         # sid → NSTextField del lado
        self._fila_boton = {}    # sid → NSButton invisible que arma la captura
        self._teclado_marco = None  # NSView del fondo del teclado (tests de geometría)
        self._nota_huerfana = None  # NSTextField de la fila huérfana, si la hay
        self._capturing = None    # sid en captura, o None
        self._capture_pressed = []  # teclas ya pulsadas en la captura en curso
        self._chip_font = theme.sf(_CHIP_FONT_PT, _CHIP_PESO)
        self._field_w = 0.0       # ancho compartido del campo (field_width)
        self._reset_boton = None  # NSButton "Reset to defaults"
        self._error_text = ""
        self._error = None        # NSTextField del mensaje de error de la fila
        self._slider = None       # NSSlider del delay de Dictation
        self._delay_ticks = []    # NSTextField × 5: las marcas 0/200/400/600/800 ms
        self._delay_valor = None  # NSTextField del valor elegido ('400 ms')
        # HotkeyManager real, si lo hay: lo conecta quien wire esta ventana en
        # el menú de la app (Task 11) con attachHotkey_(). None en los tests
        # (y en verificar-ventana.py) — sin él, begin_capture_/cancel_capture_
        # solo mueven el estado de la ventana, sin tocar pynput.
        self._hotkey = None
        self._build()
        return self

    # ---------- hotkey real (pynput) ----------
    def attachHotkey_(self, hotkey):
        """Conecta el HotkeyManager de verdad que ya está corriendo.

        Nunca instancia ni arranca un HotkeyManager: usa el que le pasan.
        Solo puede haber un keyboard.Listener en el proceso (dos hacen que
        pynput llame a TIS/TSM desde dos hilos y HIToolbox aborta con
        SIGABRT) — begin_capture()/end_capture() del que ya corre solo
        cambian a qué callback van las pulsaciones, no crean ni reinician el
        listener.
        """
        self._hotkey = hotkey

    def _build(self):
        self._win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        self._win.setTitle_("Shortcuts")
        self._win.setReleasedWhenClosed_(False)
        self._win.setDelegate_(self)
        self._win.setBackgroundColor_(theme.PAGE_BG)
        content = self._win.contentView()

        content.addSubview_(theme.label(
            NSMakeRect(PAD, y_(28, 24), W - PAD * 2, 24),
            "Shortcuts", theme.sf(19, 0.35), theme.INK))
        content.addSubview_(theme.label(
            NSMakeRect(PAD, y_(54, 17), W - PAD * 2, 17),
            "Click a shortcut, then press the keys you want to use.",
            theme.sf(12.5), theme.INK_SOFT))

        lado_font = theme.mono(9.5)
        lado_w = _lado_ancho(lado_font)   # una sola vez: mismo ancho en las 4 filas
        # Ancho del campo de chips, también compartido por las cuatro filas.
        self._field_w = field_width(self._estado, self._chip_font)

        self._keys = {}          # nombre → NSView de la casilla
        self._legends = {}       # nombre → NSTextField con la leyenda de la casilla
        self._build_keyboard(content, top=84, height=228)
        self._paint_keyboard()

        top = 330   # el teclado de la Task 9 ocupa de 84 a 312
        for sid, sc in shortcuts.SHORTCUTS.items():
            # Dictation es la única fila con slíder (sc.has_delay) y necesita
            # _DELAY_ROW_EXTRA_H de más para que quepa DENTRO de su propio
            # frame (ver _build_row); las demás se quedan en ROW_H. Sumar el
            # mismo alto que de verdad se usó al avanzar `top` es lo que
            # impide que la fila siguiente invada ese espacio de más.
            alto_fila = ROW_H + _DELAY_ROW_EXTRA_H if sc.has_delay else ROW_H
            fila = self._build_row(
                sid, NSMakeRect(PAD, y_(top, alto_fila), W - PAD * 2, alto_fila),
                lado_font, lado_w)
            content.addSubview_(fila)
            self._rows[sid] = fila
            content.addSubview_(theme.rule(
                NSMakeRect(PAD, y_(top + alto_fila, 1), W - PAD * 2, 1), theme.HAIRLINE))
            top += alto_fila + 1

        # Mensaje de error/aviso de la fila en captura (shortcuts.validate()
        # o el rechazo del llamador vía on_change). Uno solo para toda la
        # ventana: como solo una fila puede estar en captura a la vez, el
        # mensaje siempre pertenece a esa fila aunque el campo viva fuera de
        # su rectángulo.
        #
        # Finding 3 del review: el informe midió "los tres mensajes reales
        # de shortcuts.validate", pero _error_text también lleva los de
        # keys.validate_custom() -son justo los que salen al capturar una
        # sola tecla, ver apply_capture_-, y el peor caso real de los DOS
        # validadores juntos se quedaba a menos de 9pt del borde en una
        # sola línea. Dos líneas (multiline=True, _make_multiline ya existe
        # en theme.py) le dan aire de verdad en vez de vivir al filo; el
        # alto sale de _alto_multilinea(), medido con las métricas reales
        # del font, no de doblar a ojo el 17 de antes. El "top" (H-46) no
        # se toca: al crecer el alto, el campo gana espacio hacia ABAJO
        # -hacia el borde de la ventana, donde no hay nada más-, nunca
        # hacia arriba, donde vive la última fila de atajos.
        # El botón de Reset ocupa la esquina inferior derecha; el campo de
        # error cede exactamente ese ancho (sigue dando a dos líneas y el
        # test del peor caso vigila que el texto más largo quepa igual).
        reset_font = theme.sf(11.5)
        reset_w = math.ceil(theme.text_width(_RESET_TXT, reset_font)) + 26
        error_font = theme.sf(11.5)
        error_h = _alto_multilinea(error_font, 2)
        self._error = theme.label(
            NSMakeRect(PAD, y_(H - 46, error_h), W - PAD * 2 - reset_w - 12, error_h),
            "", error_font, theme.TEAL_DARK, multiline=True)
        content.addSubview_(self._error)

        # Píldora dibujada a mano + botón invisible encima, el mismo patrón
        # que las filas: en este macOS el bezel nativo de NSButton no compone
        # (verificado con screencapture: el título quedaba flotando sin caja,
        # ilegible sobre el papel — la misma familia de fallo que la pista
        # del NSSlider más arriba).
        pill = NSView.alloc().initWithFrame_(
            NSMakeRect(W - PAD - reset_w, y_(H - 42, 26), reset_w, 26))
        pill.setWantsLayer_(True)
        pill.layer().setBackgroundColor_(theme.KEYCAP_BG.CGColor())
        pill.layer().setCornerRadius_(13.0)
        pill.layer().setBorderWidth_(1.0)
        pill.layer().setBorderColor_(theme.BTN_BORDER.CGColor())
        pill.addSubview_(theme.label(
            NSMakeRect(0, (26 - 15) / 2, reset_w, 15), _RESET_TXT, reset_font,
            theme.INK_SOFT, align=NSTextAlignmentCenter))
        boton_reset = NSButton.alloc().initWithFrame_(
            NSMakeRect(0, 0, reset_w, 26))
        boton_reset.setBordered_(False)
        boton_reset.setBezelStyle_(0)
        boton_reset.setTitle_("")
        boton_reset.setTarget_(self)
        boton_reset.setAction_("resetDefaults:")
        pill.addSubview_(boton_reset)
        content.addSubview_(pill)
        self._reset_boton = boton_reset

    def _build_row(self, sid, frame, lado_font, lado_w):
        sc = shortcuts.SHORTCUTS[sid]
        row = NSView.alloc().initWithFrame_(frame)
        # Capa propia para poder resaltar la fila ENTERA durante la captura
        # (feedback: no se veía en qué fila estabas). En reposo pinta el
        # mismo papel que la ventana, así que no se nota que existe.
        row.setWantsLayer_(True)
        row.layer().setCornerRadius_(8.0)
        row.layer().setBackgroundColor_(theme.PAGE_BG.CGColor())
        rw = frame.size.width

        # Solo Dictation desplaza su contenido: el resto de filas mide
        # ROW_H (dy=0, sin cambios). Con dy=_DELAY_ROW_EXTRA_H, el título/
        # subtítulo/keycap/lado terminan EXACTAMENTE donde estarían en una
        # fila normal de ROW_H (el frame creció por abajo, no por arriba: ver
        # _build), y la banda [0, dy) que queda libre debajo es donde vive el
        # slíder — dentro del frame de la fila, no fuera de él.
        dy = _DELAY_ROW_EXTRA_H if sc.has_delay else 0

        nombres = list(self._estado.get(sid, {}).get("keys") or [])

        # Zona derecha de la fila, de DERECHA a IZQUIERDA: [campo de chips]
        # [lado]. El campo (ancho único self._field_w, ver field_width) lleva
        # dentro un chip por tecla y el lápiz ✎ — la afordancia de editar,
        # estilo Wispr. El click de verdad lo recibe el botón invisible de
        # toda la fila, más abajo.
        field_x = rw - _LADO_MARGEN_D - self._field_w
        lado_x = field_x - _LADO_GAP - lado_w
        # Título/subtítulo: hasta la etiqueta de lado con holgura. Dinámico =
        # nunca se solapan aunque el campo crezca con un combo largo.
        titulo_w = max(80, lado_x - 8)

        row.addSubview_(theme.label(
            NSMakeRect(0, 24 + dy, titulo_w, 17), sc.label, theme.sf(13.5, 0.3), theme.INK))
        row.addSubview_(theme.label(
            NSMakeRect(0, 6 + dy, titulo_w, 16), sc.subtitle, theme.sf(11.5), theme.INK_MUTED))

        campo = NSView.alloc().initWithFrame_(
            NSMakeRect(field_x, (ROW_H - _FIELD_H) / 2 + dy, self._field_w, _FIELD_H))
        campo.setWantsLayer_(True)
        campo.layer().setBackgroundColor_(theme.KEYCAP_BG.CGColor())
        campo.layer().setCornerRadius_(8.0)
        campo.layer().setBorderWidth_(1.0)
        campo.layer().setBorderColor_(theme.BTN_BORDER.CGColor())
        # Una captura con muchas teclas no puede desbordar el campo y pisar
        # el borde de la ventana: se recorta dentro.
        campo.layer().setMasksToBounds_(True)
        row.addSubview_(campo)
        self._fields[sid] = campo

        lapiz = theme.label(
            NSMakeRect(self._field_w - _FIELD_PAD - _PENCIL_W, (_FIELD_H - 16) / 2,
                       _PENCIL_W, 16),
            _PENCIL_TXT, theme.sf(12), theme.INK_MUTED)
        campo.addSubview_(lapiz)
        self._pencils[sid] = lapiz

        hint = theme.label(
            NSMakeRect(_FIELD_PAD, (_FIELD_H - 15) / 2,
                       self._field_w - 2 * _FIELD_PAD - _PENCIL_W, 15),
            _FIELD_HINT, theme.sf(11), theme.INK_MUTED)
        hint.setHidden_(True)
        campo.addSubview_(hint)
        self._hints[sid] = hint

        self._rebuild_chips(sid)

        lado = theme.label(NSMakeRect(lado_x, 17 + dy, lado_w, _LADO_ALTO),
                           side_label(sid, nombres),
                           lado_font, theme.INK_MUTED)
        row.addSubview_(lado)
        self._sides[sid] = lado

        # Toda la fila arma la captura al pulsarla (Task 10: "clicking a row
        # starts key capture"), no solo el keycap — un botón invisible del
        # tamaño de la banda de contenido (0..ROW_H, nunca la banda del
        # slíder) puesto ENCIMA de las etiquetas para recibir el click. Se
        # añade antes que el slíder (más abajo) para que este quede por
        # delante en esa banda si algún día se solapasen; hoy no lo hacen
        # -viven en bandas [0,dy) y [dy,dy+ROW_H) disjuntas- así que el orden
        # es solo cinturón y tirantes.
        boton = NSButton.alloc().initWithFrame_(NSMakeRect(0, dy, rw, ROW_H))
        boton.setBordered_(False)
        boton.setBezelStyle_(0)
        boton.setTitle_("")
        boton.setTarget_(self)
        boton.setAction_("filaClicked:")
        row.addSubview_(boton)
        self._fila_boton[sid] = boton

        if sc.has_delay:
            # macOS 26 (Darwin 25, el mismo que obligó a NSWindow en vez de
            # NSPanel) dibuja un NSSlider recién creado como el pomo solo,
            # SIN el surco: verificado con screencapture, un círculo blanco
            # flotando bajo "Hold to talk" y ni rastro de pista aunque se
            # mire pixel a pixel. stringValue()/doubleValue() sí funcionan
            # -el control responde-, solo su dibujado nativo no se ve. Una
            # pista propia, dibujada a mano y por DEBAJO del NSSlider real
            # (que sigue siendo el que recibe el arrastre), deja esto legible
            # sin depender de que AppKit pinte lo que promete.
            pista_y = _DELAY_SLIDER_Y + 9   # centro vertical del slíder
            pista = theme.rule(NSMakeRect(6, pista_y, 168, 2), theme.BTN_BORDER)
            row.addSubview_(pista)

            sl = NSSlider.alloc().initWithFrame_(
                NSMakeRect(0, _DELAY_SLIDER_Y, 180, 20))
            sl.setMinValue_(0.0)
            sl.setMaxValue_(float(shortcuts.MAX_DELAY_MS))
            sl.setNumberOfTickMarks_(5)          # 0 / 200 / 400 / 600 / 800
            sl.setAllowsTickMarkValuesOnly_(True)
            ms_inicial = int(self._estado.get(sid, {}).get("delay_ms") or 0)
            sl.setDoubleValue_(float(ms_inicial))
            sl.setTarget_(self)
            sl.setAction_("sliderMoved:")
            row.addSubview_(sl)
            self._slider = sl

            # Finding 1 (CRÍTICO) del review: el slíder no enseñaba ningún
            # número -ni marcas (setNumberOfTickMarks_ tampoco pinta nada en
            # este macOS, igual que la pista) ni el valor elegido-. Elegir
            # un delay era adivinar, no elegir. Lo que faltaba:
            #
            # 1. Las marcas, debajo de la pista, en las posiciones REALES
            #    del pomo: _marca_x() lee knobRectFlipped_ del propio
            #    slíder en vez de repartir el ancho del control a partes
            #    iguales (rectOfTickMarkAtIndex_ existe pero no descuenta
            #    el ancho del pomo y da una numeración que ya no coincide
            #    con dónde se ve -o se vería- de verdad).
            # 2. El valor en texto, a la derecha, en teal y negrita.
            #
            # Los dos anchos se miden con theme.text_width(), no a ojo: la
            # misma lección de _lado_ancho() y _nota_huerfana_ancho() de
            # más arriba en este módulo -un campo ajustado de menos recorta
            # el texto en silencio y stringValue() sigue devolviendo el
            # texto completo.
            #
            # OJO, esto mordió de verdad: con align=NSTextAlignmentCenter y
            # un campo ajustado al ancho medido + holgura, "200" se pintaba
            # "20" -comprobado con screencapture a pixel, no era una
            # ilusión de la captura de pantalla-, aunque theme.text_width()
            # midiera bien y stringValue() siguiera devolviendo "200". La
            # celda centrada calcula su propio ancho "natural" para
            # centrar, más ancho que el medido, y si el campo no le sobra
            # ese margen recorta un carácter aunque el campo mida de sobra
            # para el ancho REAL del texto (aislado en una ventana de
            # prueba: el mismo texto con align IZQUIERDA en el mismo campo
            # de 24pt no recortaba nada). Por eso aquí NO se usa align=
            # Center: se centra a mano -el origen x resta el ancho medido
            # del texto (sin holgura) entre dos, no el ancho del campo- y
            # se deja la etiqueta en alineación izquierda, que es la que de
            # verdad no recorta.
            marca_font = theme.sf(_DELAY_MARCA_PT)
            self._delay_ticks = []
            marcas = _marcas_delay()
            for i, ms in enumerate(marcas):
                texto = _fmt_delay(ms) if i == len(marcas) - 1 else str(ms)
                ancho_texto = theme.text_width(texto, marca_font)
                ancho_campo = math.ceil(ancho_texto) + _DELAY_MARCA_HOLGURA
                cx = self._marca_x(sl, ms)
                marca = theme.label(
                    NSMakeRect(cx - ancho_texto / 2, _DELAY_MARCA_Y, ancho_campo, _DELAY_MARCA_H),
                    texto, marca_font, theme.INK_MUTED)
                row.addSubview_(marca)
                self._delay_ticks.append(marca)

            valor_font = theme.sf(_DELAY_VALOR_PT, _DELAY_VALOR_PESO)
            valor_w = _valor_ancho(valor_font)
            self._delay_valor = theme.label(
                NSMakeRect(180 + _DELAY_VALOR_GAP, _DELAY_SLIDER_Y, valor_w, 20),
                _fmt_delay(ms_inicial), valor_font, theme.TEAL)
            row.addSubview_(self._delay_valor)

        return row

    def _marca_x(self, sl, ms):
        """Centro (eje x) del pomo real de `sl` en el valor `ms`.

        NSSlider no pinta ni pista ni marcas en este macOS (ver el
        comentario grande de _build_row), pero el pomo SÍ responde de
        verdad al valor -stringValue()/doubleValue() funcionan-, así que su
        rectángulo (knobRectFlipped_) es la posición real a la que hay que
        alinear la marca, no un reparto a partes iguales del ancho del
        control: rectOfTickMarkAtIndex_ existe pero mide la pista completa
        sin descontar el ancho del pomo, y da una numeración que ya no
        coincide con dónde se ve -o se vería, si este macOS pintase algo-
        el pomo de verdad (comprobado a mano con las dos: para un slíder de
        180pt con pomo de 20pt, rectOfTickMarkAtIndex_ reparte 0/45/90/135/
        180 pero el pomo real viaja de 10 a 170).

        Sube y baja doubleValue_ para leerlo y lo deja como estaba: es una
        consulta, no un cambio de estado, y no dispara sliderMoved_ porque
        setDoubleValue_ nunca manda la acción (solo lo hace un arrastre de
        verdad o un sendAction_to_ explícito).
        """
        anterior = sl.doubleValue()
        sl.setDoubleValue_(float(ms))
        rect = sl.cell().knobRectFlipped_(True)
        sl.setDoubleValue_(anterior)
        return rect.origin.x + rect.size.width / 2.0

    def _build_keyboard(self, content, top, height):
        """Dibuja el teclado. Las casillas (y sus leyendas) se crean UNA vez y
        luego solo se recolorean: añadir y quitar subviews en cada repintado
        es lo que hace parpadear una ventana.

        Las filas salen de keyboard_rows(self._estado), no de KEYBOARD_ROWS
        directamente (Task 9 fix2, Defecto 1): así, si el estado trae una
        tecla asignada que el retrato de MacBook no dibuja, aparece en una
        fila extra en vez de quedarse encendida en la lista y ausente aquí.
        alto_fila se calcula sobre len(filas), no sobre una constante, para
        que la fila extra reparta el alto disponible con las demás sin que
        haga falta agrandar la ventana.

        Una casilla sin leyenda no dice qué tecla es — encendida o no, hay
        que contar posiciones en la fila para saberlo, que es exactamente lo
        que un teclado dibujado existe para evitar. Cada casilla NOMBRADA
        lleva su leyenda, construida con key_label([nombre]): la misma
        función que ya pintan los keycaps de las cuatro filas, para que el
        teclado y la lista no puedan tener dos ideas distintas de cómo se
        escribe una tecla. Las casillas de RELLENO ("") se quedan sin
        leyenda: hoy KEYBOARD_ROWS ya no tiene ninguna (Defectos 3 y 4 de
        esta ronda), pero la rama se deja como red de seguridad por si algún
        retrato futuro vuelve a necesitar un hueco puramente decorativo.

        Un nombre `None` (Task 9, tercera ronda, Defecto 1) es distinto de
        "": cuenta para el reparto de ancho de la fila -para que las
        casillas huérfanas no hereden el ancho que se le reserva- pero no
        dibuja NADA, ni siquiera una casilla apagada; si dibujara una
        casilla vacía sería el mismo "agujero sin leyenda que parece tecla
        rota" que evita el caso `""`. Por eso el bucle lo salta antes de
        crear la NSView.
        """
        filas = keyboard_rows(self._estado)
        marco = NSView.alloc().initWithFrame_(
            NSMakeRect(PAD, y_(top, height), W - PAD * 2, height))
        marco.setWantsLayer_(True)
        marco.layer().setBackgroundColor_(theme.KEYCAP_BG.CGColor())
        marco.layer().setCornerRadius_(10.0)
        marco.layer().setBorderWidth_(1.0)
        marco.layer().setBorderColor_(theme.DIVIDER.CGColor())
        content.addSubview_(marco)
        self._teclado_marco = marco

        leyenda_font = theme.sf(_LEYENDA_TECLADO_PT, 0.2)
        leyenda_h = leyenda_font.pointSize() + 8
        nota_font = theme.sf(_NOTA_HUERFANA_PT)
        nota_w = _nota_huerfana_ancho(nota_font)

        # La fila huérfana es siempre la última de keyboard_rows() cuando la
        # hay (ver su docstring): compararla contra KEYBOARD_ROWS, no contra
        # un índice clavado, es lo que deja este bucle correcto tanto si hoy
        # hay una fila huérfana como si algún día KEYBOARD_ROWS gana una fila
        # de verdad y dejan de coincidir en longitud.
        indice_huerfana = len(filas) - 1 if len(filas) > len(KEYBOARD_ROWS) else -1

        ancho = marco.frame().size.width - 16
        alto_fila = (height - 16) / len(filas)
        for i, fila in enumerate(filas):
            total = sum(w for _, w in fila)
            x = 8.0
            fy = height - 8 - (i + 1) * alto_fila
            cy = alto_fila - 4
            for nombre, w in fila:
                kw = (ancho * w / total) - 3
                kw = max(kw, 4)
                if nombre is None:
                    x += kw + 3
                    continue
                casilla = NSView.alloc().initWithFrame_(
                    NSMakeRect(x, fy + 2, kw, cy))
                casilla.setWantsLayer_(True)
                casilla.layer().setCornerRadius_(4.0)
                marco.addSubview_(casilla)
                if nombre:
                    self._keys[nombre] = casilla
                    leyenda = theme.label(
                        NSMakeRect(0, (cy - leyenda_h) / 2, kw, leyenda_h),
                        key_label([nombre]), leyenda_font, theme.INK_KEYCAP,
                        align=NSTextAlignmentCenter)
                    casilla.addSubview_(leyenda)
                    self._legends[nombre] = leyenda
                else:
                    _apagar(casilla)
                x += kw + 3

            if i == indice_huerfana:
                # Defecto 2 de la tercera ronda: decir por qué esa tecla está
                # sola ahí. El hueco reservado por el `None` de arriba es
                # justo el sitio para el texto -a la derecha, en el mismo
                # gris secundario que ya usa la etiqueta de lado (side_label)
                # de las cuatro filas de abajo.
                nota = theme.label(
                    NSMakeRect(8 + ancho - _NOTA_HUERFANA_MARGEN_D - nota_w,
                               fy + 2 + (cy - (nota_font.pointSize() + 8)) / 2,
                               nota_w, nota_font.pointSize() + 8),
                    NOTA_HUERFANA, nota_font, theme.INK_MUTED,
                    align=NSTextAlignmentRight)
                marco.addSubview_(nota)
                self._nota_huerfana = nota

    def _paint_keyboard(self):
        """Recolorea las casillas según self._estado. DEBE correr en el hilo
        principal: lo llama también la captura, que llega por el hilo del
        listener de pynput.

        La leyenda se recolorea en la misma rama que el relleno de su
        casilla, nunca en un paso aparte: dictation enciende en teal
        SÓLIDO (theme.TEAL) y ahí el gris oscuro de una leyenda apagada
        (theme.INK_KEYCAP) sería ilegible, así que pasa a theme.PAGE_BG
        (el "papel" casi blanco de la marca). El resto de atajos encienden
        en un teal muy claro (theme.MODEL_BTN_BG) — ahí el mismo gris
        oscuro de siempre ya se lee bien, así que su leyenda se queda
        igual que una apagada. Tenerlo en la misma rama que
        setBackgroundColor_ es lo que impide que relleno y leyenda se
        desincronicen si mañana cambia uno de los dos colores.

        Con una captura armada, el teclado cambia de pregunta: deja de contar
        "qué hay asignado" y pasa a contar "qué puedes elegir" — ver
        _paint_keyboard_captura. apply/cancel repintan al salir de la captura
        y este método vuelve a la vista por asignaciones.
        """
        if self._capturing:
            self._paint_keyboard_captura(self._capturing)
            return
        encendidas = lit_keys(self._estado)
        for nombre, casilla in self._keys.items():
            sid = encendidas.get(nombre)
            leyenda = self._legends.get(nombre)
            if sid == "dictation":
                casilla.layer().setBackgroundColor_(theme.TEAL.CGColor())
                casilla.layer().setBorderWidth_(1.0)
                casilla.layer().setBorderColor_(theme.TEAL_DARK.CGColor())
                if leyenda is not None:
                    leyenda.setTextColor_(theme.PAGE_BG)
            elif sid:
                casilla.layer().setBackgroundColor_(theme.MODEL_BTN_BG.CGColor())
                casilla.layer().setBorderWidth_(1.0)
                casilla.layer().setBorderColor_(theme.MODEL_BTN_BORDER.CGColor())
                if leyenda is not None:
                    leyenda.setTextColor_(theme.INK_KEYCAP)
            else:
                _apagar(casilla)
                if leyenda is not None:
                    leyenda.setTextColor_(theme.INK_KEYCAP)

    def _paint_keyboard_captura(self, sid):
        """Verde DE VERDAD = usable para este atajo; gris = no.

        La verdad la pone shortcuts.validate — el mismo validador que luego
        acepta o rechaza la captura, así que el color y el resultado no pueden
        contarse historias distintas. El primer intento pintaba las usables
        con MODEL_BTN_BG (#EDF5F3), que en pantalla no se distingue del gris
        de una apagada — Eduardo lo describió como "el teclado se ve completo
        y las que se pueden no están marcadas". El contraste ES el arreglo:
        las usables se encienden en el teal SÓLIDO de la marca con la leyenda
        en color papel; las teclas ya PULSADAS de esta captura suben a
        TEAL_DARK (feedback en vivo: lo que marcas se refleja aquí); y el
        resto se apaga con la leyenda en gris tenue — letras, reservadas
        (esc/shift), teclas de otros atajos y las decorativas (⇪, flechas).
        Los combos (ctrl+shift+m) se siguen capturando aunque sus letras
        salgan grises: el color habla de la tecla SOLA.
        DEBE correr en el hilo principal, como _paint_keyboard.
        """
        pulsadas = {keys.canon(n) or n for n in self._capture_pressed}
        for nombre, casilla in self._keys.items():
            leyenda = self._legends.get(nombre)
            if nombre in pulsadas:
                casilla.layer().setBackgroundColor_(theme.TEAL_DARK.CGColor())
                casilla.layer().setBorderWidth_(1.0)
                casilla.layer().setBorderColor_(theme.TEAL_DARK.CGColor())
                if leyenda is not None:
                    leyenda.setTextColor_(theme.PAGE_BG)
            elif shortcuts.validate(sid, [nombre], self._estado)[0]:
                casilla.layer().setBackgroundColor_(theme.TEAL.CGColor())
                casilla.layer().setBorderWidth_(1.0)
                casilla.layer().setBorderColor_(theme.TEAL_DARK.CGColor())
                if leyenda is not None:
                    leyenda.setTextColor_(theme.PAGE_BG)
            else:
                _apagar(casilla)
                if leyenda is not None:
                    leyenda.setTextColor_(theme.INK_MUTED)

    # ---------- captura ----------
    def filaClicked_(self, sender):
        """Acción del botón invisible de cada fila: clicar en cualquier
        punto de la fila (no solo el keycap) arma su captura."""
        for sid, boton in self._fila_boton.items():
            if boton is sender:
                self.begin_capture_(sid)
                return

    @objc.python_method
    def begin_capture_(self, sid):
        """Arma la fila `sid` para recibir la próxima combinación.

        @objc.python_method: sin él, PyObjC lee el nombre como el selector
        Objective-C "begin:capture:" (CADA guion bajo -no solo el final- abre
        un keyword nuevo; ver default_selector en objc/_transform.py) y
        `objc.BadPrototypeError` revienta al definir la clase, porque ese
        selector pide 2 argumentos y el método solo recibe uno (`sid`). Nada
        de esta ventana invoca estos cuatro métodos vía un target/action de
        Cocoa -los llama solo Python (los tests, filaClicked_,
        _on_captured_)-, así que no necesitan ser selectores de verdad.

        Si hay un HotkeyManager real conectado (attachHotkey_), desvía
        también las pulsaciones globales hacia _on_captured_: es la única
        vía de captura, reutiliza el begin_capture() del listener que ya
        corre en vez de crear uno propio (ver attachHotkey_).
        """
        anterior = self._capturing
        self._capturing = sid
        self._capture_pressed = []
        # Guía clara mientras captura (punto 5 del feedback): el keycap pone
        # "…" y poco más orientaba; ahora el campo de estado dice qué hacer y
        # que Esc deja el atajo como estaba. Se limpia al terminar la captura.
        self._error_text = (
            f"Press the keys for {shortcuts.SHORTCUTS[sid].label}… "
            f"(Esc to keep the current one)"
        )
        if anterior and anterior != sid:
            # Cambiar de fila a mitad de captura no puede dejar el keycap
            # anterior encallado en "…": esa fila ya no es la que se está
            # capturando y tiene que volver a mostrar su tecla de verdad.
            self._refresh_row(anterior)
        self._refresh_row(sid)
        # El teclado pasa a la vista de captura: usables en verde, resto en
        # gris (ver _paint_keyboard_captura). Cambiar de fila a mitad de
        # captura también repinta — cada atajo tiene sus propias usables.
        self._paint_keyboard()
        if self._hotkey is not None:
            self._hotkey.begin_capture(self._on_captured_)

    @objc.python_method
    def cancel_capture_(self):
        """Esc durante la captura: deja el atajo como estaba (convención de
        macOS). También lo llama el cierre de la ventana."""
        sid, self._capturing = self._capturing, None
        self._capture_pressed = []
        self._error_text = ""
        if self._hotkey is not None:
            self._hotkey.end_capture()
        if sid:
            self._refresh_row(sid)
            self._paint_keyboard()  # vuelve la vista por asignaciones

    @objc.python_method
    def _on_captured_(self, names):
        """El `cb` de verdad que hotkey.begin_capture() invoca. Llega por el
        hilo del listener de pynput, nunca el principal — tocar AppKit aquí
        directamente es el SIGTRAP/EXC_BREAKPOINT de siempre, así que todo lo
        que sigue pasa por AppHelper.callAfter.

        Esc aborta la captura en vez de ofrecerse como tecla nueva (la misma
        convención que documenta cancel_capture_): sin este corte, "cancel"
        -que ya es esc de fábrica- sería el único atajo que se puede
        reasignar con Esc, y en cualquier otra fila un Esc de pánico se
        leería como un intento de asignación en vez de como "olvídalo".
        """
        from PyObjCTools import AppHelper

        if names and names[-1] == "esc":
            AppHelper.callAfter(self.cancel_capture_)
            return
        AppHelper.callAfter(self.apply_capture_, list(names))

    @objc.python_method
    def apply_capture_(self, names):
        """Valida y aplica lo capturado. No aplica nada que no pase por
        shortcuts.validate() ni que el llamador rechace."""
        sid = self._capturing
        if not sid:
            return
        # Lo pulsado hasta ahora se refleja en vivo: chips en el campo de la
        # fila y casillas en TEAL_DARK en el teclado, pase o no la validación.
        self._capture_pressed = list(names)
        ok, msg = shortcuts.validate(sid, list(names), self._estado)
        if not ok:
            self._error_text = msg
            self._refresh_row(sid)
            self._paint_keyboard()
            return

        fila = dict(self._estado.get(sid, {}))
        fila["keys"] = list(names)
        if shortcuts.SHORTCUTS[sid].has_delay:
            fila["delay_ms"] = delay_for(list(names), int(fila.get("delay_ms") or 0))

        aplicado, aviso = self._on_change(sid, fila)
        if not aplicado:
            # El hotkey rechazó el cambio: el estado de la ventana refleja lo
            # que suena de verdad, nunca lo que se pidió.
            self._error_text = aviso
            self._refresh_row(sid)
            return

        self._estado[sid] = fila
        self._capturing = None
        self._capture_pressed = []
        self._error_text = aviso or msg    # msg puede traer el aviso de F5 o fn
        if self._hotkey is not None:
            self._hotkey.end_capture()
        self._refresh_row(sid)
        self._layout_fields()   # un combo más largo (o más corto) recoloca la columna
        self._paint_keyboard()
        if fila.get("delay_ms") is not None and self._slider is not None and sid == "dictation":
            self._slider.setDoubleValue_(float(fila["delay_ms"]))
            self._actualizar_valor_delay(int(fila["delay_ms"]))

    @objc.python_method
    def set_delay_(self, ms):
        """El slíder. Solo Dictation lo tiene (shortcuts.SHORTCUTS[…].has_delay)."""
        ms = max(0, min(shortcuts.MAX_DELAY_MS, int(ms)))
        fila = dict(self._estado.get("dictation", {}))
        fila["delay_ms"] = ms
        aplicado, aviso = self._on_change("dictation", fila)
        if not aplicado:
            self._error_text = aviso
            return
        self._estado["dictation"] = fila
        self._actualizar_valor_delay(ms)
        self._refresh_row("dictation")

    def sliderMoved_(self, sender):
        self.set_delay_(int(round(sender.doubleValue())))

    def _actualizar_valor_delay(self, ms):
        """Sincroniza el texto del valor ('400 ms') con el delay real.

        Se llama tanto desde set_delay_ (arrastrar el slíder) como desde
        apply_capture_ (el salto automático a shortcuts.DEFAULT_DELAY_MS al
        elegir una tecla con guarda, ver delay_for): las dos vías cambian
        delay_ms, y las dos tienen que dejar el número visible de acuerdo
        con el estado, o el Finding 1 del review volvería a repetirse por
        otro camino.
        """
        if self._delay_valor is not None:
            self._delay_valor.setStringValue_(_fmt_delay(ms))

    def _rebuild_chips(self, sid, nombres=None):
        """Rehace los chips del campo de `sid`: con `nombres` None pinta el
        binding del estado; con lista (la captura en vivo) pinta esa.

        A diferencia de las casillas del teclado, los chips sí se recrean en
        cada repintado: su NÚMERO cambia con el binding. Solo se tocan los de
        la fila afectada, así que no hay parpadeo que temer.
        """
        campo = self._fields.get(sid)
        if campo is None:
            return
        for chip in self._chips.get(sid, ()):
            chip.removeFromSuperview()
        if nombres is None:
            nombres = list(self._estado.get(sid, {}).get("keys") or [])
        textos = chip_texts(nombres)
        chips = []
        x = _FIELD_PAD
        cy = (_FIELD_H - _CHIP_H) / 2
        for t in textos:
            chip = theme.keycap(
                NSMakeRect(x, cy, _chip_ancho(t, self._chip_font), _CHIP_H),
                t, self._chip_font, 5)
            campo.addSubview_(chip)
            chips.append(chip)
            x += _chip_ancho(t, self._chip_font) + _CHIP_GAP
        self._chips[sid] = chips
        hint = self._hints.get(sid)
        if hint is not None:
            # El placeholder solo durante la captura y hasta la primera tecla.
            hint.setHidden_(bool(textos) or self._capturing != sid)

    def _layout_fields(self):
        """Recoloca los cuatro campos cuando cambia el ancho compartido (un
        combo nuevo más largo, o un reset que lo encoge). La etiqueta de lado
        se mueve con ellos: la columna entera viaja junta, como en _build_row.
        """
        nuevo = field_width(self._estado, self._chip_font)
        if nuevo == self._field_w:
            return
        self._field_w = nuevo
        for sid, campo in self._fields.items():
            rw = self._rows[sid].frame().size.width
            fr = campo.frame()
            campo.setFrame_(NSMakeRect(
                rw - _LADO_MARGEN_D - nuevo, fr.origin.y, nuevo, fr.size.height))
            lapiz = self._pencils.get(sid)
            if lapiz is not None:
                lf = lapiz.frame()
                lapiz.setFrame_(NSMakeRect(
                    nuevo - _FIELD_PAD - _PENCIL_W, lf.origin.y,
                    lf.size.width, lf.size.height))
            hint = self._hints.get(sid)
            if hint is not None:
                hf = hint.frame()
                hint.setFrame_(NSMakeRect(
                    hf.origin.x, hf.origin.y,
                    nuevo - 2 * _FIELD_PAD - _PENCIL_W, hf.size.height))
            lado = self._sides.get(sid)
            if lado is not None:
                sfr = lado.frame()
                lado.setFrame_(NSMakeRect(
                    rw - _LADO_MARGEN_D - nuevo - _LADO_GAP - sfr.size.width,
                    sfr.origin.y, sfr.size.width, sfr.size.height))
            self._rebuild_chips(sid)

    def resetDefaults_(self, _sender):
        """Vuelve los cuatro atajos a fábrica (el "Reset to default" de
        Wispr, pedido expreso de Eduardo). Cada vuelta pasa por _on_change
        igual que una captura: si el hotkey real rechaza alguna (colisión
        transitoria con un binding raro), esa fila se queda como está y el
        campo de error lo cuenta — un segundo click la suele resolver, con
        el resto ya en fábrica."""
        if self._capturing:
            self.cancel_capture_()
        avisos = []
        for sid, sc in shortcuts.SHORTCUTS.items():
            fila = dict(self._estado.get(sid, {}))
            fila["keys"] = list(sc.default)
            if sc.has_delay:
                fila["delay_ms"] = delay_for(list(sc.default), 0)
                if fila.get("style") not in keys.MODES:
                    fila["style"] = shortcuts.DEFAULT_STYLE
            aplicado, aviso = self._on_change(sid, fila)
            if not aplicado:
                avisos.append(aviso)
                continue
            self._estado[sid] = fila
        self._error_text = avisos[0] if avisos else ""
        for sid in shortcuts.SHORTCUTS:
            self._refresh_row(sid)
        self._layout_fields()
        self._paint_keyboard()
        if self._slider is not None:
            ms = int(self._estado.get("dictation", {}).get("delay_ms") or 0)
            self._slider.setDoubleValue_(float(ms))
            self._actualizar_valor_delay(ms)

    def _refresh_row(self, sid):
        """Repinta una fila entera: resaltado, campo de chips, lado y mensaje.

        DEBE correr en el hilo principal: apply_capture_ lo llama desde el
        callback de captura, que llega por el hilo del listener de pynput.
        Escribir en AppKit desde ahí es el SIGTRAP de siempre.
        """
        nombres = list(self._estado.get(sid, {}).get("keys") or [])
        capturando = self._capturing == sid
        fila = self._rows.get(sid)
        if fila is not None and fila.layer() is not None:
            # La fila en captura se resalta ENTERA — antes solo cambiaba el
            # borde del keycap y no se veía dónde estabas.
            fila.layer().setBackgroundColor_(
                (theme.MODEL_BTN_BG if capturando else theme.PAGE_BG).CGColor())
        campo = self._fields.get(sid)
        if campo is not None:
            campo.layer().setBorderColor_(
                (theme.TEAL if capturando else theme.BTN_BORDER).CGColor())
            campo.layer().setBorderWidth_(2.0 if capturando else 1.0)
        self._rebuild_chips(sid, self._capture_pressed if capturando else None)
        lado = self._sides.get(sid)
        if lado is not None:
            lado.setStringValue_(side_label(sid, nombres))
        if self._error is not None:
            self._error.setStringValue_(self._error_text)

    # ---------- ciclo de vida ----------
    def show(self):
        # Voooxly es una app de menu-bar: makeKeyAndOrderFront() solo no le
        # roba el foco a la app que estaba delante y la ventana se abre
        # DETRÁS (el usuario la pierde de vista). Activar la app la pone
        # delante; orderFrontRegardless es el cinturón para el caso en que
        # activate no baste (espacios de trabajo, apps en pantalla completa).
        from AppKit import NSApp

        self._win.center()
        NSApp.activateIgnoringOtherApps_(True)
        self._win.makeKeyAndOrderFront_(None)
        self._win.orderFrontRegardless()

    def close(self):
        try:
            self._win.close()
        except Exception:
            log.debug("close() de la ventana de Shortcuts falló", exc_info=True)

    def windowShouldClose_(self, _sender):
        # Cerrar la ventana a mitad de captura no puede dejar el listener de
        # pynput desviado para siempre hacia una ventana que ya no existe.
        if self._capturing:
            self.cancel_capture_()
        return True
