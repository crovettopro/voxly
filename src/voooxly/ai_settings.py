"""Qué proveedor eligió el usuario, guardado en prefs.json.

Separado de app.py a propósito: instanciar VoooxlyApp construye menús de AppKit
y no se puede hacer en un test. Aquí solo hay diccionarios.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import providers

CLAVE_PROVEEDOR = "ai_provider"
CLAVE_BASE_URL = "ai_base_url"
CLAVE_MODELO = "ai_model"


@dataclass(frozen=True)
class Selection:
    provider: providers.Provider
    base_url: str
    model: str


def load(prefs: dict) -> Selection | None:
    """La elección guardada, o None si no hay ninguna válida."""
    key = prefs.get(CLAVE_PROVEEDOR)
    if not key:
        return None
    prov = providers.get(key)
    if prov is None:
        # Un preset retirado en una versión posterior no puede tumbar el arranque.
        return None
    return Selection(
        provider=prov,
        base_url=prefs.get(CLAVE_BASE_URL) or prov.base_url,
        model=prefs.get(CLAVE_MODELO) or prov.default_model,
    )


def save(prefs: dict, provider_key: str, base_url: str, model: str) -> dict:
    """Devuelve prefs con la elección puesta. No escribe a disco."""
    prov = providers.get(provider_key)
    if prov is None:
        raise ValueError(f"Proveedor desconocido: {provider_key!r}")
    prefs = dict(prefs)
    prefs[CLAVE_PROVEEDOR] = prov.key
    prefs[CLAVE_BASE_URL] = base_url or prov.base_url
    prefs[CLAVE_MODELO] = model or prov.default_model
    return prefs
