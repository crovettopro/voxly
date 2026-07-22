"""La paleta y los widgets base, compartidos entre las dos ventanas.

Se extraen de onboarding.py para que settings_window.py no los duplique: dos
copias de la paleta se desincronizan en el primer retoque de marca y acabas
con dos ventanas de colores distintos en la misma app.

Estos tests construyen objetos AppKit de verdad, como los de onboarding.
"""
from voooxly import theme


def test_la_paleta_de_marca_existe_entera():
    for nombre in (
        "TEAL", "TEAL_DARK", "INK", "INK_SOFT", "INK_MUTED", "INK_KEYCAP",
        "PAGE_BG", "HAIRLINE", "DIVIDER", "BTN_BORDER", "BTN_GHOST_TEXT",
        "KEYCAP_BG", "KEYCAP_BG2", "KEYCAP_EDGE",
    ):
        assert getattr(theme, nombre) is not None, nombre


def test_hex_parsea_el_teal_de_marca():
    c = theme.hex_("#107A69")
    assert abs(c.redComponent() - 0x10 / 255.0) < 0.01
    assert abs(c.greenComponent() - 0x7A / 255.0) < 0.01


def test_label_construye_un_campo_no_editable():
    from Foundation import NSMakeRect

    f = theme.label(NSMakeRect(0, 0, 100, 20), "Dictation", theme.sf(13))
    assert f.stringValue() == "Dictation"
    assert not f.isEditable()


def test_onboarding_sigue_usando_la_misma_paleta():
    # El objetivo del refactor: una sola fuente de color. Si onboarding se
    # quedara con una copia propia, este test lo caza.
    from voooxly import onboarding

    assert onboarding.TEAL is theme.TEAL
    assert onboarding.PAGE_BG is theme.PAGE_BG
