"""Reglas de mostrador: cuándo cotizar, cuándo pedir un dato, cuándo pasar a un vendedor."""

from __future__ import annotations

import unicodedata

HANDOFF_REPLY = (
    "Dale, te dejo con un vendedor del local para esto. "
    "En un rato te escriben por acá."
)

_HANDOFF = (
    "vendedor",
    "persona",
    "humano",
    "hablar con alguien",
    "quiero hablar",
    "asesor",
    "gerente",
    "reclamo",
    "queja",
    "garantia",
    "garantía",
    "mayorista",
    "factura a",
    "siniestro",
    "a pedido",
)


def fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def wants_human(text: str) -> bool:
    blob = fold(text)
    return any(phrase in blob for phrase in _HANDOFF)
