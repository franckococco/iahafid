"""Reglas de mostrador: cuándo cotizar, cuándo pedir chasis, cuándo pasar a un vendedor."""

from __future__ import annotations

import re
import unicodedata

HANDOFF_REPLY = (
    "Dale, te dejo con un vendedor del local para esto. "
    "En un rato te escriben por acá."
)

ASK_CHASSIS_REPLY = (
    "Para esa pieza en el local usamos el número de chasis, el de la cédula o el parabrisas, "
    "no el de motor. ¿Me lo pasás? Con eso te ubico mejor."
)

GOT_CHASSIS_ONLY = (
    "Dale, anoté el chasis. ¿Qué pieza estás buscando para ese auto?"
)

RESET_REPLY = (
    "Dale, arrancamos de cero. ¿Qué pieza necesitás y para qué auto? "
    "Si es compleja, pasame el número de chasis."
)

_RESET = (
    "nuevo pedido",
    "nueva consulta",
    "otra consulta",
    "otro pedido",
    "otro auto",
    "empezar de nuevo",
    "arrancar de nuevo",
    "reiniciar",
    "reset",
    "olvidate",
    "de cero",
)

_PHOTO = (
    "foto",
    "imagen",
    "despiece",
    "captura",
    "dibujo",
    "lamina",
    "lámina",
    "screenshot",
    "mandame la foto",
    "manda la foto",
    "el dibujo",
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

# VIN de 17 (sin I, O, Q). En mostrador a veces mandan los últimos 8 si dicen "chasis".
_VIN_CHARS = re.compile(r"^[A-HJ-NPR-Z0-9]{8,17}$", re.IGNORECASE)
_PREFIXES = (
    "VF3",
    "VF7",
    "VF8",
    "WVW",
    "WV1",
    "WV2",
    "WV3",
    "9BW",
    "8AP",
    "8AW",
    "3VW",
    "1VW",
)
_HINT = re.compile(
    r"\b(chasis|chassis|vin|nro\.?\s*(de\s*)?chasis|numero\s+de\s+chasis)\b",
    re.IGNORECASE,
)
_MOTOR_HINT = re.compile(r"\b(motor|nro\.?\s*(de\s*)?motor|numero\s+de\s+motor)\b", re.IGNORECASE)


def fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def wants_human(text: str) -> bool:
    blob = fold(text)
    return any(phrase in blob for phrase in _HANDOFF)


def wants_reset(text: str) -> bool:
    blob = fold(text)
    return any(fold(phrase) in blob for phrase in _RESET)


def wants_photo(text: str) -> bool:
    blob = fold(text)
    return any(fold(phrase) in blob for phrase in _PHOTO)


def extract_chassis(text: str) -> str | None:
    """Saca número de chasis. No toma nro de motor aunque lo escriban."""
    if _MOTOR_HINT.search(text) and not _HINT.search(text):
        return None
    tokens = re.findall(r"[A-Za-z0-9]+", text)
    for token in tokens:
        code = token.upper()
        if len(code) == 17 and _looks_like_chassis(code):
            return code
    compact = re.sub(r"[\s\-]", "", text).upper()
    for prefix in _PREFIXES:
        idx = compact.find(prefix)
        if idx >= 0 and idx + 17 <= len(compact):
            candidate = compact[idx : idx + 17]
            if _looks_like_chassis(candidate) and len(candidate) == 17:
                return candidate
    if _HINT.search(text):
        for token in tokens:
            code = token.upper()
            if code in {"CHASIS", "CHASSIS", "VIN", "NUMERO", "NRO"}:
                continue
            if 8 <= len(code) <= 17 and _looks_like_chassis(code):
                return code
    return None


def _looks_like_chassis(code: str) -> bool:
    if not _VIN_CHARS.match(code):
        return False
    if code.isdigit() or code.isalpha():
        return False
    return any(ch.isalpha() for ch in code) and any(ch.isdigit() for ch in code)


def needs_chassis(matches: list[dict]) -> bool:
    if not matches:
        return False
    tipo = fold(str(matches[0].get("tipo") or "rapido"))
    if tipo == "complejo":
        return True
    top = matches[:3]
    productos = {fold(str(item.get("producto") or "")) for item in top}
    skus = {str(item.get("sku") or "") for item in top}
    return len(skus) > 1 and len(productos) == 1


def handoff_reply(chasis: str = "") -> str:
    if chasis:
        return (
            f"Listo, anoté el chasis {chasis}. "
            "Te dejo con un vendedor para ubicar la pieza exacta. En un rato te escriben."
        )
    return HANDOFF_REPLY


_PIECE_STOP = {
    "hola",
    "buenas",
    "buen",
    "dia",
    "dias",
    "tardes",
    "noches",
    "tenes",
    "tiene",
    "hay",
    "para",
    "por",
    "una",
    "el",
    "la",
    "los",
    "las",
    "de",
    "del",
    "un",
    "me",
    "te",
    "se",
    "che",
    "chasis",
    "chassis",
    "vin",
    "numero",
    "nro",
    "necesitaria",
    "necesito",
    "queria",
    "quisiera",
    "busco",
    "buscar",
    "sale",
    "cuanto",
    "cuales",
    "productos",
    "stock",
    "foto",
    "imagen",
    "despiece",
    "captura",
    "dibujo",
    "pasame",
    "mandame",
    "manda",
    "mandar",
    "favor",
    "please",
    "podes",
    "podrias",
    "podria",
    "enviar",
    "envia",
    "enviane",
    "estoy",
    "necesitando",
    "codigo",
    "repuesto",
    "si",
    "nuevo",
    "pedido",
    "consulta",
    "reset",
}

# Con el chasis ya está el auto: no mandar marca/modelo a PartsLink24.
_VEHICLE_NOISE = {
    "amarok",
    "gol",
    "trend",
    "peugeot",
    "citroen",
    "volkswagen",
    "vw",
    "audi",
    "308",
    "c3",
    "auto",
    "camioneta",
}


_YEAR_TOKEN = re.compile(r"^\d{4}$")


def piece_query(text: str, chasis: str = "") -> str:
    """Texto de la pieza, sin el chasis ni el saludo."""
    blob = text
    if chasis:
        blob = re.sub(re.escape(chasis), " ", blob, flags=re.IGNORECASE)
    found = extract_chassis(text)
    if found:
        blob = re.sub(re.escape(found), " ", blob, flags=re.IGNORECASE)
    tokens = [
        token
        for token in fold(blob).replace("?", " ").replace(".", " ").replace(",", " ").split()
        if len(token) > 1
        and token not in _PIECE_STOP
        and token not in _VEHICLE_NOISE
        and not token.isdigit()
        and not _YEAR_TOKEN.match(token)
    ]
    return " ".join(tokens)


def last_piece_query(user_messages: list[str], current: str, chasis: str = "") -> str:
    """La pieza de ESTE pedido, no la de un chat anterior (filtro 308 + amortiguador)."""
    for msg in [current, *reversed(user_messages)]:
        if extract_chassis(msg) and not piece_query(msg, chasis):
            continue
        query = piece_query(msg, chasis)
        if query:
            return query
    return ""


def local_quote_ok(matches: list[dict]) -> bool:
    """Hay un ítem rápido único: se cotiza en el local, sin PartsLink24."""
    if len(matches) != 1:
        return False
    return not needs_chassis(matches)


def chassis_context(chasis: str) -> str:
    if not chasis:
        return (
            "El cliente todavía no dio número de chasis. "
            "Pedilo SOLO si la pieza es compleja o hay más de una opción. "
            "Nunca pidas número de motor."
        )
    return (
        f"El cliente ya dio el número de chasis: {chasis}. "
        "No lo vuelvas a pedir. Nunca pidas número de motor. "
        "Si la pieza es rápida, cotizá igual; el chasis queda anotado."
    )
