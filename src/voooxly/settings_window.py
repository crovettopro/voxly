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
    NSTextAlignmentCenter,
    NSTextAlignmentRight,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRect, NSObject

from . import shortcuts, theme

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
_LADO_GAP = 4       # hueco entre el keycap y la etiqueta de lado
_LADO_MARGEN_D = 4  # hueco entre la etiqueta de lado y el borde de la fila
_KEYCAP_W = 62
_KEYCAP_H = 26

# Tamaño de la leyenda de cada casilla del teclado visual. 9pt le sobra hueco
# incluso al texto más ancho ("F13") en la casilla más estrecha del teclado
# (~30pt de ancho real, medido con theme.text_width): no hace falta ganar
# tamaño de ventana para que se lea.
_LEYENDA_TECLADO_PT = 9.0


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


# Teclado de un MacBook, por filas. (nombre pynput o "" si no es asignable,
# ancho relativo). El nombre "" son teclas de relleno: se dibujan para que el
# teclado se reconozca de un vistazo, pero nunca se encienden.
#
# Las letras y dígitos se nombran (con el char en minúscula que reporta
# hotkey._norm) y no solo "m": shortcuts.py no restringe qué tecla puede
# entrar en un combo de varias teclas (solo valida la tecla suelta), así que
# cycle_mode se puede reasignar a cualquier ctrl+alt+<letra> — si el teclado
# solo supiera encender "m", esa reasignación se vería en la fila pero nunca
# en el dibujo, rompiendo la regla de que las dos vistas son la misma verdad.
#
# La puntuación (-, =, [, ], \, ;, ', ,, ., /) y las dos teclas especiales de
# la fila de abajo (⇪ caps lock, fn) SÍ se nombran, aunque ninguna sea
# asignable hoy (Task 9, Defecto 2): sin nombre se pintaban como rectángulos
# en blanco y en la captura de pantalla se leían como teclas rotas, no como
# "esto no se puede asignar". Nombrarlas les da leyenda vía key_label() sin
# encenderlas nunca (lit_keys() nunca las incluye porque ningún atajo puede
# apuntar a ellas — ver keys.validate_custom). Quedan dos casillas SIN
# nombre a propósito, y no por descuido: la de la fila de números (no hay
# una tecla real ahí, solo hueco de más) y la ancha del final de la fila de
# abajo (el bloque de flechas, que son varias teclas y no una sola).
KEYBOARD_ROWS: list[list[tuple[str, float]]] = [
    [("esc", 1.4)] + [(f"f{i}", 1.0) for i in range(1, 13)] + [("f13", 1.0)],
    [(d, 1.0) for d in "1234567890"] + [("-", 1.0), ("=", 1.0), ("", 1.0)] + [("backspace", 1.5)],
    [("tab", 1.5)] + [(c, 1.0) for c in "qwertyuiop"] + [("[", 1.0), ("]", 1.0)] + [("\\", 1.2)],
    [("caps_lock", 1.7)] + [(c, 1.0) for c in "asdfghjkl"] + [(";", 1.0), ("'", 1.0)] + [("enter", 1.6)],
    [("shift", 2.2)] + [(c, 1.0) for c in "zxcvbnm"] + [(",", 1.0), (".", 1.0), ("/", 1.0)] + [("shift_r", 2.2)],
    [("fn", 1.1), ("ctrl", 1.1), ("alt", 1.1), ("cmd", 1.4), ("space", 5.6),
     ("cmd_r", 1.4), ("alt_r", 1.1), ("", 2.2)],
]

# Quién gana cuando dos atajos comparten una tecla física. Dictation primero:
# es la que el usuario busca de un vistazo, y sin una regla explícita el color
# dependería del orden de iteración del diccionario.
_PRIORIDAD = ("dictation", "cancel", "latch", "cycle_mode")


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
        self._keycaps = {}       # sid → NSTextField del keycap
        self._sides = {}         # sid → NSTextField del lado
        self._teclado_marco = None  # NSView del fondo del teclado (tests de geometría)
        self._build()
        return self

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

        self._keys = {}          # nombre → NSView de la casilla
        self._legends = {}       # nombre → NSTextField con la leyenda de la casilla
        self._build_keyboard(content, top=84, height=228)
        self._paint_keyboard()

        top = 330   # el teclado de la Task 9 ocupa de 84 a 312
        for sid in shortcuts.SHORTCUTS:
            fila = self._build_row(
                sid, NSMakeRect(PAD, y_(top, ROW_H), W - PAD * 2, ROW_H), lado_font, lado_w)
            content.addSubview_(fila)
            self._rows[sid] = fila
            content.addSubview_(theme.rule(
                NSMakeRect(PAD, y_(top + ROW_H, 1), W - PAD * 2, 1), theme.HAIRLINE))
            top += ROW_H + 1

    def _build_row(self, sid, frame, lado_font, lado_w):
        sc = shortcuts.SHORTCUTS[sid]
        row = NSView.alloc().initWithFrame_(frame)
        rw = frame.size.width

        row.addSubview_(theme.label(
            NSMakeRect(0, 24, rw - 150, 17), sc.label, theme.sf(13.5, 0.3), theme.INK))
        row.addSubview_(theme.label(
            NSMakeRect(0, 6, rw - 150, 16), sc.subtitle, theme.sf(11.5), theme.INK_MUTED))

        nombres = list(self._estado.get(sid, {}).get("keys") or [])

        # La columna del lado se reserva primero, con el ancho ya calculado
        # para caber cualquiera de sus cuatro valores posibles, y el keycap
        # se cuelga a su izquierda con el mismo hueco de siempre. lado_w es
        # igual en las cuatro filas, así que cap_x también lo es — la
        # columna de keycaps queda alineada pase lo que pase el texto de
        # cada fila.
        lado_x = rw - _LADO_MARGEN_D - lado_w
        cap_x = lado_x - _LADO_GAP - _KEYCAP_W

        cap = theme.keycap(NSMakeRect(cap_x, 12, _KEYCAP_W, _KEYCAP_H),
                           key_label(nombres), theme.sf(14, 0.3), 7)
        row.addSubview_(cap)
        self._keycaps[sid] = cap

        lado = theme.label(NSMakeRect(lado_x, 17, lado_w, _LADO_ALTO),
                           side_label(sid, nombres),
                           lado_font, theme.INK_MUTED)
        row.addSubview_(lado)
        self._sides[sid] = lado
        return row

    def _build_keyboard(self, content, top, height):
        """Dibuja el teclado. Las casillas (y sus leyendas) se crean UNA vez y
        luego solo se recolorean: añadir y quitar subviews en cada repintado
        es lo que hace parpadear una ventana.

        Una casilla sin leyenda no dice qué tecla es — encendida o no, hay
        que contar posiciones en la fila para saberlo, que es exactamente lo
        que un teclado dibujado existe para evitar. Cada casilla NOMBRADA
        lleva su leyenda, construida con key_label([nombre]): la misma
        función que ya pintan los keycaps de las cuatro filas, para que el
        teclado y la lista no puedan tener dos ideas distintas de cómo se
        escribe una tecla. Las casillas de RELLENO ("") se quedan sin
        leyenda: existen solo para que el contorno del teclado se reconozca
        de un vistazo (ver el comentario de KEYBOARD_ROWS) y, como nunca se
        pueden asignar ni encender, ponerles una letra sería inventar una
        segunda tabla de símbolos — justo lo que este módulo lleva toda la
        tarde evitando.
        """
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

        ancho = marco.frame().size.width - 16
        alto_fila = (height - 16) / len(KEYBOARD_ROWS)
        for i, fila in enumerate(KEYBOARD_ROWS):
            total = sum(w for _, w in fila)
            x = 8.0
            fy = height - 8 - (i + 1) * alto_fila
            for nombre, w in fila:
                kw = (ancho * w / total) - 3
                kw = max(kw, 4)
                cy = alto_fila - 4
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
        """
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

    # ---------- ciclo de vida ----------
    def show(self):
        self._win.makeKeyAndOrderFront_(None)
        self._win.center()

    def close(self):
        try:
            self._win.close()
        except Exception:
            log.debug("close() de la ventana de Shortcuts falló", exc_info=True)

    def windowShouldClose_(self, _sender):
        return True
