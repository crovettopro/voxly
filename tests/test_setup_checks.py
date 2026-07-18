from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from dictador import setup_checks


@contextmanager
def fake_state(mic=True, acc=True, model=True, ai=True):
    """Parchea las cuatro sondas del sistema para testear la lógica sin tocar macOS."""
    with ExitStack() as stack:
        for name, value in (
            ("has_microphone", mic),
            ("has_accessibility", acc),
            ("has_model", model),
            ("has_ai_engine", ai),
        ):
            stack.enter_context(patch.object(setup_checks, name, return_value=value))
        yield


def test_check_all_devuelve_los_cuatro_pasos_en_orden():
    with fake_state():
        checks = setup_checks.check_all()
    assert [c.key for c in checks] == ["mic", "accessibility", "model", "ai"]
    assert all(c.ok for c in checks)


def test_el_motor_de_ia_no_es_bloqueante():
    """Sin IA la app dicta igual en modo Verbatim: no debe frenar el arranque."""
    with fake_state(ai=False):
        checks = {c.key: c for c in setup_checks.check_all()}
        assert checks["ai"].blocking is False
        assert checks["ai"].ok is False
        assert setup_checks.needs_setup() is False


def test_needs_setup_true_si_falta_accesibilidad():
    with fake_state(acc=False):
        assert setup_checks.needs_setup() is True


def test_needs_setup_true_si_falta_el_modelo():
    with fake_state(model=False):
        assert setup_checks.needs_setup() is True


def test_needs_setup_true_si_falta_el_microfono():
    with fake_state(mic=False):
        assert setup_checks.needs_setup() is True


def test_has_model_delega_en_stt():
    with patch("dictador.stt.find_model", return_value="/ruta/modelo.bin"):
        assert setup_checks.has_model() is True
    with patch("dictador.stt.find_model", return_value=None):
        assert setup_checks.has_model() is False


def test_has_ai_engine_true_si_algun_backend_esta_vivo():
    with patch("dictador.refine.health", return_value={"ollama": False, "claude": True, "openai": False}):
        assert setup_checks.has_ai_engine() is True
    with patch("dictador.refine.health", return_value={"ollama": False, "claude": False, "openai": False}):
        assert setup_checks.has_ai_engine() is False


def test_has_ai_engine_no_lanza_si_health_falla():
    with patch("dictador.refine.health", side_effect=OSError("boom")):
        assert setup_checks.has_ai_engine() is False
