"""El Controller de pynput se construye UNA vez, y desde el main thread.

Contexto: Controller.__init__ consulta la distribución de teclado vía TIS/TSM.
paste_frontmost lo construía en cada pegado, desde el hilo worker de _process.
Si eso coincide con otro hilo tocando TSM (el listener del hotkey), HIToolbox
mata el proceso: SIGTRAP en dispatch_assert_queue, sin excepción de Python que
poder atrapar. Crash real el 2026-07-20 17:09:08, justo tras un dictado.

press()/release() solo usan el mapping ya cacheado, así que construirlo una vez
al arrancar (main thread) saca TSM de la ruta de pegado.
"""

import pytest

from voooxly import output


class FakeController:
    """Cuenta construcciones: cada una sería una consulta a TSM."""

    construcciones = 0

    def __init__(self):
        type(self).construcciones += 1

    def press(self, _k):
        pass

    def release(self, _k):
        pass


@pytest.fixture(autouse=True)
def controller_limpio(monkeypatch):
    import pynput.keyboard

    FakeController.construcciones = 0
    monkeypatch.setattr(pynput.keyboard, "Controller", FakeController)
    monkeypatch.setattr(output, "_kb", None)
    yield
    monkeypatch.setattr(output, "_kb", None)


def test_pegar_varias_veces_construye_el_controller_una_sola_vez():
    for _ in range(5):
        assert output.paste_frontmost() is True
    assert FakeController.construcciones == 1


def test_warmup_deja_el_controller_listo_para_que_el_pegado_no_toque_tsm():
    assert output.warmup() is True
    assert FakeController.construcciones == 1

    output.paste_frontmost()
    assert FakeController.construcciones == 1, "el pegado reconstruyó el Controller"


def test_warmup_dos_veces_no_reconstruye():
    output.warmup()
    output.warmup()
    assert FakeController.construcciones == 1


def test_warmup_no_lanza_si_pynput_falla(monkeypatch):
    """Un fallo al preparar no puede tumbar el arranque de la app."""
    import pynput.keyboard

    class Explota:
        def __init__(self):
            raise RuntimeError("sin Accesibilidad")

    monkeypatch.setattr(pynput.keyboard, "Controller", Explota)
    assert output.warmup() is False
