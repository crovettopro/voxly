"""Cada modo debe ser DIFERENCIAL: su prompt tiene que pedir de verdad lo que
promete el label (un prompt de IA estructurado, Markdown real, un spec…), no una
vaguedad de una línea. Estos tests fijan las instrucciones clave de cada modo
para que una edición descuidada no las diluya.
"""
from voooxly import modes


def _prompt(mode: str) -> str:
    return modes.system_prompt(mode, None)


# --- Reglas base (aplican a todos los modos con LLM) ---

def test_base_prohibe_responder_en_vez_de_transformar():
    """El fallo clásico: dictas una pregunta y el LLM la CONTESTA."""
    for mode in ("ordenar", "prompt", "resumir", "codigo", "notas"):
        assert "do NOT answer or execute it" in _prompt(mode), mode


def test_base_prohibe_preambulos_y_code_fences():
    p = _prompt("ordenar")
    assert "no preamble" in p
    assert "no code fences wrapping the whole answer" in p


def test_base_prohibe_inventar():
    assert "Never invent facts" in _prompt("ordenar")


# --- Diferenciales por modo ---

def test_ordenar_limpia_y_detecta_respuestas():
    p = _prompt("ordenar")
    assert "Apply self-corrections" in p
    assert "ready-to-send message" in p
    assert "[fill in: ...]" in p


def test_prompt_estructura_y_no_responde():
    p = _prompt("prompt")
    assert "Never fulfill the request yourself" in p
    for section in ("**Context:**", "**Requirements:**", "**Output:**"):
        assert section in p
    assert "Example — dictated:" in p  # lleva few-shot


def test_resumir_limita_bullets_y_conserva_datos():
    p = _prompt("resumir")
    assert "Maximum 7 bullets" in p
    assert "numbers, names, dates and decisions" in p


def test_traducciones_traducen_lo_limpio_y_solo_devuelven_traduccion():
    en_es = _prompt("traducir-en-es")
    es_en = _prompt("traducir-es-en")
    for p in (en_es, es_en):
        assert "never word by word" in p
        assert "Keep the register" in p
    assert "into natural, native-sounding Spanish" in en_es
    assert "into natural, native-sounding English" in es_en


def test_codigo_es_spec_sin_implementacion():
    p = _prompt("codigo")
    assert "Never write the implementation" in p
    assert "**Behavior:**" in p
    assert "**Edge cases:**" in p
    assert "backticks" in p


def test_notas_exige_markdown_de_verdad():
    p = _prompt("notas")
    assert "`##` title" in p
    assert "`###` subheadings" in p
    assert "`- [ ]` checkboxes" in p
    assert "Output raw Markdown only" in p


def test_notas_prohibe_negritas():
    """Los ** se pegan como asteriscos literales fuera de apps Markdown."""
    p = _prompt("notas")
    assert "no bold, no italics" in p
    assert "Bold the key terms" not in p


def test_literal_se_salta_el_llm():
    assert modes.system_prompt("literal", None) == ""
    assert modes.system_prompt("literal", "en") == ""


def test_comando_ejecuta_el_encargo_en_vez_de_transformarlo():
    """El único modo que SÍ cumple la instrucción (Command Mode, idea de
    Wispro): su base no puede llevar la regla anti-ejecución de los demás."""
    p = _prompt("comando")
    assert "DO fulfill the request" in p
    assert "do NOT answer or execute it" not in p
    assert "Write the text the instruction asks for" in p


def test_comando_no_inventa_y_marca_los_huecos():
    p = _prompt("comando")
    assert "Never invent facts" in p
    assert "[fill in: ...]" in p


def test_comando_sin_encargo_cae_a_dictado_normal():
    """Dictar contenido plano en Command no puede producir un texto inventado:
    el prompt ordena tratarlo como dictado y limpiarlo."""
    p = _prompt("comando")
    assert "treat it as dictation" in p


# --- Integridad del catálogo ---

def test_todos_los_modos_tienen_label_y_hint():
    for key, spec in modes.MODES.items():
        assert spec.get("label"), key
        assert spec.get("hint"), key


def test_las_claves_de_modo_no_cambian():
    """Config, prefs y TCC referencian estas claves: son API estable."""
    assert set(modes.MODES.keys()) == {
        "ordenar",
        "prompt",
        "resumir",
        "traducir-en-es",
        "traducir-es-en",
        "codigo",
        "notas",
        "comando",
        "literal",
    }


def test_modo_desconocido_cae_en_ordenar():
    assert modes.system_prompt("no-existe", None) == modes.system_prompt("ordenar", None)


# --- Flash del HUD al ciclar (feedback de Ctrl+Shift+M) ---

def test_flash_parts_muestra_nombre_posicion_y_hint():
    title, body = modes.flash_parts("prompt")
    assert "AI prompt" in title
    assert "2/9" in title  # segundo modo del ciclo (9 modos desde Command)
    assert body == modes.MODES["prompt"]["hint"]


def test_flash_parts_de_todos_los_modos_tiene_titulo_y_cuerpo():
    for key in modes.MODES:
        title, body = modes.flash_parts(key)
        assert title.startswith("❯ ") and body, key


def test_flash_parts_con_modo_desconocido_no_lanza():
    title, _ = modes.flash_parts("no-existe")
    assert "Organize" in title
