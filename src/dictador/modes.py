"""Modos de dictado. Cada modo = un system prompt que transforma lo dictado.

Diseño inspirado en los "Writing Styles" de Wispr Flow: el modo cambia cómo se reescribe
lo que dices, no solo qué se transcribe. El LLM recibe la transcripción cruda y devuelve
el texto final listo para pegar.
"""
from __future__ import annotations

# Idioma de salida preferido. None = mantener el idioma detectado.
DEFAULT_LANG = "es"


def _base_rules(lang: str | None) -> str:
    lang_hint = f" Escribe la salida en {lang}." if lang else ""
    return (
        "Eres un editor de dictado por voz. Recibes una transcripción cruda de lo que el usuario "
        "dijo en voz alta, con muletillas, frases rotas, autocorrecciones y errores de transcripción."
        " Tu trabajo es devolver SOLO el texto final, sin explicaciones, sin prefijos, sin markdown "
        "extra a menos que el modo lo pida. Conserva la intención y la información del usuario; no "
        "inventes datos. No añadas saludos ni despedidas que el usuario no dijo salvo que el modo "
        "lo pida explícitamente." + lang_hint
    )


# Los labels/hints (UI) van en inglés; la SALIDA del dictado la gobierna
# app.language (es por defecto). Las claves no se tocan: config y TCC las usan.
# "fast_lane": True → dictados cortos (llm.fast_lane_words) se pegan sin LLM.
MODES: dict[str, dict] = {
    "ordenar": {
        "label": "Organize & reply",
        "hint": "Cleans up your speech; replies come out message-ready.",
        "fast_lane": True,
        "system": (
            "Reescribe la transcripción como texto claro y bien redactado que conserve exactamente "
            "la intención e información del usuario. Elimina muletillas ('eh', 'o sea', 'bueno'), "
            "repeticiones y falsos arranques. Resuelve autocorrecciones ('quedamos a las 5, bueno, 6' "
            "-> 'quedamos a las 6'). Corrige errores obvios de transcripción. Mantén el tono del "
            "usuario. No añadas información nueva. Si el usuario listó cosas, devuélvelas como lista. "
            "CASO ESPECIAL: si lo dictado es claramente una respuesta a un mensaje o email (el usuario "
            "se dirige a alguien o contesta algo), devuélvelo como mensaje listo para enviar: coherente "
            "y cordial, con saludo/despedida breves SOLO si el usuario los dictó o son claramente "
            "necesarios. Si falta un dato, deja [pendiente: ...] para que el usuario lo rellene."
        ),
    },
    "prompt": {
        "label": "AI prompt",
        "hint": "Shapes your dictation into a clear LLM prompt.",
        "system": (
            "Convierte la transcripción en un prompt claro, estructurado y reutilizable para otro "
            "LLM. Incluye rol, tarea, contexto y formato de salida esperado. Usa markdown con "
            "secciones si ayuda. Conserva la intención; concreta ambigüedades razonables. No añadas "
            "datos que el usuario no dio."
        ),
    },
    "resumir": {
        "label": "Summarize",
        "hint": "Condenses what you said into crisp bullets.",
        "system": (
            "Resume la transcripción en una lista de bullets concisos que capturen las ideas "
            "principales. Máximo 7 bullets. Sin preámbulo."
        ),
    },
    "traducir-en-es": {
        "label": "Translate EN→ES",
        "hint": "Speak English, paste Spanish.",
        "stt_lang": "en",  # aquí el usuario dicta en inglés: forzar "es" lo rompería
        "system": (
            "Traduce la transcripción del inglés al español conservando tono y muletillas mínimas. "
            "Devuelve solo la traducción."
        ),
    },
    "traducir-es-en": {
        "label": "Translate ES→EN",
        "hint": "Speak Spanish, paste English.",
        "system": (
            "Traduce la transcripción del español al inglés conservando tono y muletillas mínimas. "
            "Devuelve solo la traducción."
        ),
    },
    "codigo": {
        "label": "Code / spec",
        "hint": "Turns dictation into a code spec or comment.",
        "system": (
            "Convierte la transcripción en una especificación o comentario de código claro: "
            "requisitos, comportamiento esperado, casos límite. Usa markdown con bloques de código "
            "si procede. No escribas la implementación, solo el spec/comentario."
        ),
    },
    "notas": {
        "label": "Markdown notes",
        "hint": "Structures your speech as a markdown note.",
        "system": (
            "Estructura la transcripción como una nota markdown con un título H2, secciones y "
            "listas según corresponda. Conserva toda la información. Sin preámbulo."
        ),
    },
    "literal": {
        "label": "Verbatim",
        "hint": "Exactly what you said — no rewriting.",
        "system": "NONE",  # señal especial: el refinador se salta y devuelve la transcripción tal cual
    },
}


def system_prompt(mode: str, lang: str | None = DEFAULT_LANG) -> str:
    spec = MODES.get(mode, MODES["ordenar"])
    if spec["system"] == "NONE":
        return ""
    return _base_rules(lang) + "\n\n" + spec["system"]


def modes_by_key() -> dict[str, dict]:
    return {k: {"label": v["label"], "hint": v["hint"]} for k, v in MODES.items()}