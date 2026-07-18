"""Tests de la ventana de onboarding.

No se puede "mirar" una ventana desde un test, pero sí construirla de verdad e
inspeccionar su jerarquía y su lógica de estado, que es donde están los fallos
que importan: un botón apuntando a un selector inexistente (crash al pulsarlo),
una fila fuera de los límites, o dejar continuar sin un permiso imprescindible.

Requieren sesión gráfica de macOS (no corren por SSH sin ventana).
"""
from unittest.mock import patch

import pytest

pytest.importorskip("AppKit")

from AppKit import NSApplication  # noqa: E402

from dictador import onboarding, setup_checks  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _app():
    NSApplication.sharedApplication()


@pytest.fixture
def controller():
    return onboarding.OnboardingController.alloc().initWithFinish_(None)


def _state(mic=True, acc=True, model=True, ai=True):
    from contextlib import ExitStack

    stack = ExitStack()
    for name, value in (("has_microphone", mic), ("has_accessibility", acc),
                        ("has_model", model), ("has_ai_engine", ai)):
        stack.enter_context(patch.object(setup_checks, name, return_value=value))
    return stack


def test_se_construye_con_las_cuatro_filas(controller):
    assert set(controller._rows) == {"mic", "accessibility", "model", "ai"}
    for row in controller._rows.values():
        assert set(row) == {"status", "button", "bar"}


def test_cada_boton_apunta_a_un_selector_que_existe(controller):
    """Un selector mal escrito no falla al construir: revienta al pulsar el botón."""
    for key, row in controller._rows.items():
        sel = row["button"].action()
        assert controller.respondsToSelector_(sel), f"'{key}' apunta a {sel}, que no existe"


def test_ninguna_subvista_se_sale_de_la_ventana(controller):
    for sub in controller._win.contentView().subviews():
        f = sub.frame()
        assert f.origin.x >= 0 and f.origin.y >= 0
        assert f.origin.x + f.size.width <= onboarding.W + 0.5
        assert f.origin.y + f.size.height <= onboarding.H + 0.5


def test_las_filas_no_se_solapan(controller):
    h = onboarding.ROW_H - 10
    ys = sorted(s.frame().origin.y for s in controller._win.contentView().subviews()
                if abs(s.frame().size.height - h) < 0.5)
    assert len(ys) == 4
    assert all(ys[i] + h <= ys[i + 1] for i in range(len(ys) - 1))


def test_todo_cumplido_permite_continuar(controller):
    with _state():
        controller._refresh()
        assert controller._done.isEnabled()
        assert not controller._hint.isHidden()
        assert controller._rows["mic"]["status"].stringValue() == "●"


def test_sin_accesibilidad_no_deja_continuar(controller):
    with _state(acc=False):
        controller._refresh()
        assert not controller._done.isEnabled()
        assert controller._hint.isHidden()
        assert controller._rows["accessibility"]["button"].isEnabled()


def test_sin_ia_si_deja_continuar(controller):
    """El motor de IA es opcional: sin él se dicta igual en modo Verbatim."""
    with _state(ai=False):
        controller._refresh()
        assert controller._done.isEnabled()
        assert controller._rows["ai"]["button"].isEnabled()


def test_finish_invoca_el_callback():
    llamado = []
    c = onboarding.OnboardingController.alloc().initWithFinish_(lambda: llamado.append(1))
    c.finish_(None)
    assert llamado == [1]


def test_finish_no_revienta_si_el_callback_falla():
    def _explota():
        raise RuntimeError("boom")

    c = onboarding.OnboardingController.alloc().initWithFinish_(_explota)
    c.finish_(None)  # no debe propagar
