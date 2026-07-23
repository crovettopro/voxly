"""El cuerpo del POST a /chat/completions según el modelo.

El fallo real de Eduardo: gpt-5-mini devolvía 400 Bad Request mientras
gpt-4.1-mini conectaba. Los modelos razonadores de OpenAI (gpt-5*, o1*, o3*,
o4*) solo aceptan la temperature por defecto: mandarles otra es un 400. El
payload vive en una función pura para que este contrato quede clavado aquí.
"""
from voooxly import refine


def _body(model):
    return refine.openai_payload(model, "sys", "user", 0.3)


def test_los_razonadores_no_llevan_temperature():
    for m in ("gpt-5-mini", "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.4-mini",
              "o3-mini", "o4-mini", "o1"):
        assert "temperature" not in _body(m), m


def test_el_resto_conserva_su_temperature():
    for m in ("gpt-4.1-mini", "gpt-4o-mini", "llama-3.3-70b-versatile",
              "gemini-3.6-flash", "gemini-2.5-flash"):
        assert _body(m)["temperature"] == 0.3, m


def test_el_payload_lleva_modelo_y_mensajes_en_orden():
    body = _body("gpt-4.1-mini")
    assert body["model"] == "gpt-4.1-mini"
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["messages"][0]["content"] == "sys"
    assert body["messages"][1]["content"] == "user"


def test_un_modelo_que_solo_empieza_parecido_no_se_confunde():
    # "o1" es prefijo peligroso: "olmo-7b" no es un razonador de OpenAI y
    # quitarle la temperature cambiaría su salida en silencio.
    assert "temperature" in _body("olmo-7b")
    assert "temperature" in _body("gpt-4o")
