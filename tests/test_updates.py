from unittest.mock import MagicMock, patch

from dictador import updates


def test_is_newer_compara_numericamente_no_alfabeticamente():
    assert updates.is_newer("1.10.0", "1.9.0") is True  # alfabéticamente "1.10" < "1.9"
    assert updates.is_newer("1.0.1", "1.0.0") is True
    assert updates.is_newer("1.0.0", "1.0.0") is False
    assert updates.is_newer("0.9.0", "1.0.0") is False


def test_is_newer_tolera_versiones_raras():
    assert updates.is_newer("1.2", "1.1.9") is True
    assert updates.is_newer("1.0", "1.0.0") is False
    assert updates.is_newer("basura", "1.0.0") is False
    assert updates.is_newer("1.0.0", "basura") is False


def test_check_devuelve_info_si_hay_version_nueva():
    resp = MagicMock(ok=True)
    resp.json.return_value = {"version": "2.0.0", "url": "https://x/y.dmg", "notes": "Nuevo"}
    with patch("dictador.updates.requests.get", return_value=resp):
        got = updates.check("https://voxly/appcast.json", "1.0.0")
    assert got["version"] == "2.0.0"
    assert got["url"] == "https://x/y.dmg"
    assert got["notes"] == "Nuevo"


def test_check_devuelve_none_si_estamos_al_dia():
    resp = MagicMock(ok=True)
    resp.json.return_value = {"version": "1.0.0", "url": "https://x/y.dmg"}
    with patch("dictador.updates.requests.get", return_value=resp):
        assert updates.check("https://voxly/appcast.json", "1.0.0") is None


def test_check_devuelve_none_si_falta_la_url():
    """Un appcast a medio publicar no debe abrir un menú que no lleva a ningún sitio."""
    resp = MagicMock(ok=True)
    resp.json.return_value = {"version": "2.0.0"}
    with patch("dictador.updates.requests.get", return_value=resp):
        assert updates.check("https://voxly/appcast.json", "1.0.0") is None


def test_check_nunca_lanza_si_no_hay_red():
    with patch("dictador.updates.requests.get", side_effect=OSError("sin red")):
        assert updates.check("https://voxly/appcast.json", "1.0.0") is None


def test_check_nunca_lanza_con_json_invalido():
    resp = MagicMock(ok=True)
    resp.json.side_effect = ValueError("no es json")
    with patch("dictador.updates.requests.get", return_value=resp):
        assert updates.check("https://voxly/appcast.json", "1.0.0") is None


def test_check_devuelve_none_si_el_servidor_responde_error():
    resp = MagicMock(ok=False)
    with patch("dictador.updates.requests.get", return_value=resp):
        assert updates.check("https://voxly/appcast.json", "1.0.0") is None


# --- download ---

def _resp_con_bytes(data: bytes, with_length: bool = True):
    """Mock de requests.get(stream=True) usable como context manager."""
    resp = MagicMock()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.raise_for_status = MagicMock()
    resp.headers = {"Content-Length": str(len(data))} if with_length else {}
    resp.iter_content = MagicMock(return_value=[data[:3], data[3:]])
    return resp


def test_download_escribe_el_dmg_y_reporta_progreso(tmp_path):
    data = b"dmg-bytes"
    seen = []
    with patch("dictador.updates.requests.get", return_value=_resp_con_bytes(data)):
        path = updates.download("https://x/y.dmg", "1.0.1", tmp_path, seen.append)
    assert path == tmp_path / "Voxly-1.0.1.dmg"
    assert path.read_bytes() == data
    assert seen[-1] == 100
    assert not (tmp_path / "Voxly-1.0.1.dmg.part").exists()


def test_download_devuelve_none_y_limpia_el_part_si_falla(tmp_path):
    resp = _resp_con_bytes(b"xx")
    resp.iter_content = MagicMock(side_effect=OSError("conexión cortada"))
    with patch("dictador.updates.requests.get", return_value=resp):
        assert updates.download("https://x/y.dmg", "1.0.1", tmp_path) is None
    assert list(tmp_path.iterdir()) == []  # ni DMG ni .part huérfano


def test_download_sin_content_length_no_rompe_el_progreso(tmp_path):
    """GitHub a veces sirve sin Content-Length: sin él no hay pct, pero sí DMG."""
    seen = []
    with patch(
        "dictador.updates.requests.get",
        return_value=_resp_con_bytes(b"dmg-bytes", with_length=False),
    ):
        path = updates.download("https://x/y.dmg", "1.0.1", tmp_path, seen.append)
    assert path is not None and path.read_bytes() == b"dmg-bytes"
    assert seen == [100]  # solo el 100 final
