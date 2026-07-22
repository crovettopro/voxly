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
