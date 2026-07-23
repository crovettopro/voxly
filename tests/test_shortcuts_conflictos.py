"""Dos atajos no pueden compartir tecla, o uno de los dos muere en silencio.

La comparación va sobre nombres CANONICALIZADOS. "cmd_l" y "cmd" son la misma
tecla física en macOS (pynput colapsa el enum), así que una matriz que
compare strings crudos dejaría pasar justo la colisión que importa: el usuario
vería dos filas distintas y una de las dos no dispararía nunca.

Los mensajes van en inglés porque salen en la ventana.
"""
from voooxly import shortcuts

ACTUALES = {
    "dictation": {"keys": ["cmd_r"], "style": "hold", "delay_ms": 0},
    "cycle_mode": {"keys": ["ctrl", "shift", "m"]},
    "latch": {"keys": ["shift"]},
    "cancel": {"keys": ["esc"]},
}


def test_una_tecla_libre_pasa():
    ok, msg = shortcuts.validate("dictation", ["alt_r"], ACTUALES)
    assert ok, msg


def test_reasignarse_su_propia_tecla_pasa():
    # Cambiar solo el delay no puede chocar consigo mismo.
    ok, _ = shortcuts.validate("dictation", ["cmd_r"], ACTUALES)
    assert ok


def test_cancel_y_latch_pueden_reasignarse_su_propia_tecla_reservada():
    """cancel y latch tienen por defecto "esc" y "shift", que son EXACTAMENTE
    las teclas que keys._RESERVADAS bloquea para dictado. El chequeo de
    autoasignación tiene que compararse contra la tecla propia ANTES de caer
    a validate_custom(), o confirmar la fila sin cambiar nada rechazaría la
    propia tecla de fábrica del atajo como si fuera ajena y reservada para
    dictado.
    """
    ok, msg = shortcuts.validate("cancel", ["esc"], ACTUALES)
    assert ok, msg

    ok, msg = shortcuts.validate("latch", ["shift"], ACTUALES)
    assert ok, msg


def test_la_tecla_de_otro_atajo_choca_y_dice_de_quien():
    ok, msg = shortcuts.validate("dictation", ["esc"], ACTUALES)
    assert not ok
    assert "Cancel dictation" in msg


def test_el_choque_se_ve_a_traves_del_alias_de_lado():
    # latch es "shift"; asignar "shift_l" a dictado es la MISMA tecla física.
    # Sin canonicalizar, esto pasaría y el latch dejaría de funcionar.
    ok, msg = shortcuts.validate("dictation", ["shift_l"], ACTUALES)
    assert not ok
    assert "Latch dictation" in msg


def test_una_tecla_de_un_solo_caracter_se_rechaza():
    ok, msg = shortcuts.validate("dictation", ["a"], ACTUALES)
    assert not ok
    assert "a" in msg


def test_una_lista_vacia_se_rechaza():
    ok, msg = shortcuts.validate("dictation", [], ACTUALES)
    assert not ok
    assert msg


def test_un_combo_que_comparte_una_tecla_con_otro_combo_no_choca():
    # ⌃⇧M y ⌃⇧V comparten ⌃ y ⇧ pero son combos distintos: no hay conflicto.
    ok, _ = shortcuts.validate("cycle_mode", ["ctrl", "shift", "p"], ACTUALES)
    assert ok


def test_un_combo_identico_a_otro_si_choca():
    otros = dict(ACTUALES, cancel={"keys": ["ctrl", "shift", "p"]})
    ok, msg = shortcuts.validate("cycle_mode", ["ctrl", "shift", "p"], otros)
    assert not ok
    assert "Cancel dictation" in msg


def test_avisa_de_f5_sin_bloquear():
    # F5 es la tecla de Dictado de macOS: mala elección documentada, pero es
    # decisión del usuario. Se avisa, no se bloquea.
    ok, msg = shortcuts.validate("dictation", ["f5"], ACTUALES)
    assert ok
    assert "F5" in msg or "f5" in msg


def test_un_modificador_izquierdo_capturado_se_acepta_con_su_aviso():
    # Desde la captura, "cmd" SIN lado es la tecla izquierda física (pynput
    # colapsa cmd_l→cmd). validate_custom la rechaza porque su público es
    # texto tecleado (config.yaml), pero rechazarla aquí dejaría el ⌘
    # izquierdo —que DICTATION_KEYS ofrece con su delay— sin camino posible
    # en la ventana: se veía gris en el teclado y la captura fallaba.
    for n in ("cmd", "alt", "ctrl"):
        ok, msg = shortcuts.validate("dictation", [n], ACTUALES)
        assert ok, n
        assert "delay" in msg.lower(), "el aviso explica el arranque con retardo"


def test_elegir_fn_aconseja_apagar_la_tecla_globo_sin_bloquear():
    # macOS también reacciona a fn/🌐 (emoji, cambio de idioma…) según lo que
    # haya en Ajustes del Sistema. Elegirla es legítimo — Wispr la trae de
    # fábrica —, así que se aconseja apagar la acción del sistema, no se
    # bloquea.
    ok, msg = shortcuts.validate("dictation", ["fn"], ACTUALES)
    assert ok
    assert "🌐" in msg or "fn" in msg.lower()
