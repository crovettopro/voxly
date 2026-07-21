"""Catálogo de proveedores de LLM.

Un preset NO es código: es un base_url y un modelo por defecto ya rellenos.
Todos los que hablan el protocolo OpenAI (kind="openai") los atiende el mismo
Refiner._openai() que ya existía, así que añadir un proveedor a esta tabla no
requiere tocar refine.py.

Lista curada y corta a propósito (MVP): los más comunes y que mejor rinden para
limpiar dictado, más Ollama como única opción local. El orden es el del menú
(orden de inserción): cloud primero, Ollama el último porque la mayoría de la
gente no corre modelos en su propia máquina, el gratis el primero de todos.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    base_url: str
    default_model: str
    needs_key: bool
    kind: str  # "ollama" | "claude" | "openai"
    note: str = ""  # "free" → se muestra en el menú; el resto, vacío


PROVIDERS: dict[str, Provider] = {
    # Groq primero: es el único gratis de la lista y la vía más rápida para
    # probar el refinado sin sacar la tarjeta. Detrás de tres de pago no lo
    # encontraba nadie.
    "groq": Provider(
        key="groq",
        label="Groq — free",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        needs_key=True,
        kind="openai",
        note="free",
    ),
    "claude": Provider(
        key="claude",
        label="Claude",
        base_url="",  # lo gestiona el SDK de anthropic
        default_model="claude-sonnet-5",
        needs_key=True,
        kind="claude",
    ),
    "openai": Provider(
        key="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        needs_key=True,
        kind="openai",
    ),
    "gemini": Provider(
        key="gemini",
        label="Google Gemini",
        # Endpoint OpenAI-compatible de Gemini: mismo camino que openai/groq.
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-2.0-flash",
        needs_key=True,
        kind="openai",
    ),
    # Ollama (local) el último: la opción para quien corre modelos en su propia
    # máquina. Sin modelo por defecto (fijar uno presupone cuál tiene instalado):
    # se le pregunta a SU Ollama (list_ollama_models) y elige el suyo.
    "ollama": Provider(
        key="ollama",
        label="Ollama (local)",
        base_url="http://localhost:11434",
        default_model="",
        needs_key=False,
        kind="ollama",
    ),
}


def get(key: str) -> Provider | None:
    return PROVIDERS.get(key)
