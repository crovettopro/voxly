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


MODES: dict[str, dict] = {
    "ordenar": {
        "label": "Ordenar ideas",
        "hint": "Limpia muletillas y estructura, sin inventar.",
        "system": (
            "Reescribe la transcripción como texto claro y bien redactado que conserve exactamente "
            "la intención e información del usuario. Elimina muletillas ('eh', 'o sea', 'bueno'), "
            "repeticiones y falsos arranques. Resuelve autocorrecciones ('quedamos a las 5, bueno, 6' "
            "-> 'quedamos a las 6'). Corrige errores obvios de transcripción. Mantén el tono del "
            "usuario. No añadas información nueva. Si el usuario listó cosas, devuélvelas como lista."
        ),
    },
    "responder": {
        "label": "Responder a personas",
        "hint": "Convierte en respuesta de email/mensaje bien redactada.",
        "system": (
            "Convierte la transcripción en una respuesta de mensaje o email clara, cordial y bien "
            "redactada, lista para enviar. Usa el tono que el usuario empleó. Si el usuario dijo "
            "puntos sueltos, ensambla un mensaje coherente que los contenga. No inventes contenido: "
            "si falta información, deja un [pendiente: ...] para que el usuario lo rellene. Saludo y "
            "despedida breves y naturales."
        ),
    },
    "prompt": {
        "label": "Prompt para IA",
        "hint": "Convierte lo dictado en un prompt claro para un LLM.",
        "system": (
            "Convierte la transcripción en un prompt claro, estructurado y reutilizable para otro "
            "LLM. Incluye rol, tarea, contexto y formato de salida esperado. Usa markdown con "
            "secciones si ayuda. Conserva la intención; concreta ambigüedades razonables. No añadas "
            "datos que el usuario no dio."
        ),
    },
    "resumir": {
        "label": "Resumir",
        "hint": "Resume lo dicho en bullets concisos.",
        "system": (
            "Resume la transcripción en una lista de bullets concisos que capturen las ideas "
            "principales. Máximo 7 bullets. Sin preámbulo."
        ),
    },
    "traducir-en-es": {
        "label": "Traducir EN→ES",
        "hint": "Traduce del inglés al español manteniendo tono.",
        "system": (
            "Traduce la transcripción del inglés al español conservando tono y muletillas mínimas. "
            "Devuelve solo la traducción."
        ),
    },
    "traducir-es-en": {
        "label": "Traducir ES→EN",
        "hint": "Traduce del español al inglés manteniendo tono.",
        "system": (
            "Traduce la transcripción del español al inglés conservando tono y muletillas mínimas. "
            "Devuelve solo la traducción."
        ),
    },
    "codigo": {
        "label": "Código / spec",
        "hint": "Convierte lo dictado en comentario o spec de código.",
        "system": (
            "Convierte la transcripción en una especificación o comentario de código claro: "
            "requisitos, comportamiento esperado, casos límite. Usa markdown con bloques de código "
            "si procede. No escribas la implementación, solo el spec/comentario."
        ),
    },
    "notas": {
        "label": "Notas Markdown",
        "hint": "Estructura como nota con headings y listas.",
        "system": (
            "Estructura la transcripción como una nota markdown con un título H2, secciones y "
            "listas según corresponda. Conserva toda la información. Sin preámbulo."
        ),
    },
    "literal": {
        "label": "Literal (sin reescritura)",
        "hint": "Solo transcribe, sin tocar el texto.",
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