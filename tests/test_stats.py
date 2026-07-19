"""Stats acumulativas: nunca lanzan, nunca pierden lo acumulado y el resumen
cuenta una historia útil ("typing saved") en vez de números crudos.
"""
from dictador import stats


def test_bump_acumula(tmp_path):
    p = tmp_path / "stats.json"
    stats.bump(10, 4.0, p)
    stats.bump(5, 2.5, p)
    s = stats.load(p)
    assert s["dictations"] == 2
    assert s["words"] == 15
    assert s["seconds_recorded"] == 6.5


def test_fichero_corrupto_reinicia_sin_lanzar(tmp_path):
    p = tmp_path / "stats.json"
    p.write_text("{roto", encoding="utf-8")
    assert stats.load(p)["dictations"] == 0
    stats.bump(3, 1.0, p)  # y bump lo repara
    assert stats.load(p) == {"dictations": 1, "words": 3, "seconds_recorded": 1.0}


def test_summary_vacio_invita_a_dictar(tmp_path):
    assert "No dictations yet" in stats.summary(tmp_path / "no-existe.json")


def test_summary_en_minutos_y_en_horas(tmp_path):
    p = tmp_path / "stats.json"
    stats.bump(400, 60.0, p)  # 400 palabras → ~7 min ahorrados
    assert "min of typing saved" in stats.summary(p)
    stats.bump(20000, 600.0, p)  # ya en horas
    out = stats.summary(p)
    assert "h of typing saved" in out
    assert "2 dictations" in out
    assert "20,400 words" in out


def test_valores_negativos_no_corrompen(tmp_path):
    p = tmp_path / "stats.json"
    stats.bump(-5, -1.0, p)
    s = stats.load(p)
    assert s["dictations"] == 1 and s["words"] == 0 and s["seconds_recorded"] == 0.0
