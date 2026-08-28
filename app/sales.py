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

NEED_DETAILS = (
    "Contame qué pieza necesitás y para qué auto. "
    "Si es compleja, pasame el chasis de la cédula o el parabrisas."
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


def brand_hint(*texts: str) -> str:
    """Marca del auto para entrar al catálogo correcto en PartsLink24."""
    blob = fold(" ".join(t for t in texts if t))
    if "peugeot" in blob:
        return "peugeot"
    if "citroen" in blob:
        return "citroen"
    if "volkswagen" in blob or re.search(r"\bvw\b", blob):
        return "volkswagen"
    return ""


def model_hint(*texts: str) -> str:
    """Modelo (207, 308…) para el catálogo Peugeot cuando el chasis es corto."""
    blob = fold(" ".join(t for t in texts if t))
    for item in (
        "2008",
        "3008",
        "5008",
        "partner",
        "rifter",
        "207",
        "208",
        "308",
        "408",
        "301",
        "206",
        "307",
        "306",
        "205",
        "108",
        "107",
        "106",
    ):
        if re.search(rf"\b{item}\b", blob):
            return item
    return ""


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
    # Pegaron solo el código (8–17), típico cuando pedimos el chasis.
    if len(tokens) == 1:
        code = tokens[0].upper()
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
    "buscando",
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
    "no",
    "paso",
    "ese",
    "esa",
    "esos",
    "esas",
    "este",
    "esta",
    "esto",
    "nuevo",
    "pedido",
    "consulta",
    "reset",
}

# Con el chasis ya está el auto: no mandar marca/modelo a PartsLink24.
_VEHICLE_NOISE = {
    "amarok",
    "bora",
    "golf",
    "vento",
    "fox",
    "suran",
    "saveiro",
    "polo",
    "passat",
    "tiguan",
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
    "axr",
    "tdi",
    "tsi",
    "fsi",
    "diesel",
    "nafta",
    "turbo",
    "8v",
    "16v",
    "20v",
}


_YEAR_TOKEN = re.compile(r"^\d{4}$")

_AXLE_FRONT = ("delantero", "adelante", "frente", "trompa")
_AXLE_REAR = ("trasero", "atras", "zaga")
_SIDE_LEFT = ("izquierdo",)
_SIDE_RIGHT = ("derecho",)
_NEED_AXLE = ("amortiguador", "elastico", "espiral", "resorte", "muehle")
_NEED_SIDE = ("faro", "piloto", "optica", "espejo", "guardabarro", "calota")
_POSITION_WORDS = _AXLE_FRONT + _AXLE_REAR + _SIDE_LEFT + _SIDE_RIGHT


def axle_wanted(query: str) -> str:
    blob = fold(query)
    if any(word in blob for word in _AXLE_FRONT):
        return "delantero"
    if any(word in blob for word in _AXLE_REAR):
        return "trasero"
    return ""


def side_wanted(query: str) -> str:
    blob = fold(query)
    if any(word in blob for word in _SIDE_LEFT):
        return "izquierdo"
    if any(word in blob for word in _SIDE_RIGHT):
        return "derecho"
    return ""


def needs_axle_clarify(query: str) -> bool:
    blob = fold(query)
    return any(word in blob for word in _NEED_AXLE) and not axle_wanted(query)


def needs_side_clarify(query: str) -> bool:
    blob = fold(query)
    return any(word in blob for word in _NEED_SIDE) and not side_wanted(query)


def is_position_only(query: str) -> bool:
    tokens = [token for token in fold(query).split() if token]
    return bool(tokens) and all(token in _POSITION_WORDS for token in tokens)


_PUMP_KIND_MARKERS = {
    "agua": ("agua", "refriger", "refrigerante", "refrigeracion"),
    "combustible": ("combustible", "gasolina", "gasoil", "nafta"),
    "aceite": ("aceite",),
    "direccion": ("direccion", "hidraulic"),
    "vacio": ("vacio",),
    "inyector": ("inyector",),
}
_FILTER_KIND_MARKERS = {
    "habitaculo": ("habitaculo", "polen", "cabina"),
    "aceite": ("aceite",),
    "aire": ("aire",),
    "combustible": ("combustible", "gasoil", "nafta"),
}
_SEARCH_PUMP = {
    "agua": "bomba para liquido refrigerante",
    "combustible": "bomba combustible",
    "aceite": "bomba aceite",
    "direccion": "bomba direccion",
    "vacio": "bomba vacio",
    "inyector": "unidad bomba inyector",
}
_KIND_WORDS = frozenset(
    marker
    for markers in (*_PUMP_KIND_MARKERS.values(), *_FILTER_KIND_MARKERS.values())
    for marker in markers
) | {
    "refrigeracion",
    "completa",
    "carcasa",
    "impulsor",
    "rodete",
    "electrica",
    "mecanica",
    "sola",
    "solo",
}
_CLARIFY_SKIP = frozenset({"si", "sip", "dale", "ok", "okay", "bien", "claro", "no"})
_VARIANT_WORDS = frozenset(
    {"completa", "carcasa", "impulsor", "rodete", "electrica", "mecanica", "sola", "solo"}
)


def pump_kind_wanted(query: str) -> str:
    blob = fold(query)
    if "bomba" not in blob:
        return ""
    for kind, markers in _PUMP_KIND_MARKERS.items():
        if any(marker in blob for marker in markers):
            return kind
    return ""


def filter_kind_wanted(query: str) -> str:
    blob = fold(query)
    if "filtro" not in blob:
        return ""
    for kind, markers in _FILTER_KIND_MARKERS.items():
        if any(marker in blob for marker in markers):
            return kind
    return ""


def piece_clarify_ask(query: str) -> str:
    """Si la pieza es ambigua, qué preguntar antes de ir al catálogo."""
    blob = fold(query)
    if "bomba" in blob and not pump_kind_wanted(query):
        return "de agua (refrigeración), de combustible, de aceite, de dirección o de vacío"
    if "filtro" in blob and not filter_kind_wanted(query):
        return "de aceite, de aire, de combustible o de habitáculo"
    return ""


def is_clarify_only(query: str) -> bool:
    """Respuesta corta a una pregunta (la de agua, refrigeración, delantera)."""
    if is_position_only(query):
        return True
    tokens = [token for token in fold(query).split() if token and token not in _CLARIFY_SKIP]
    if not tokens:
        return False
    allowed = _KIND_WORDS | set(_POSITION_WORDS)
    return all(token in allowed for token in tokens)


def merge_piece(stored: str, extra: str) -> str:
    """Junta 'bomba' + 'agua', o cambia el tipo: 'bomba agua' + 'combustible'."""
    extra_f = fold(extra).strip()
    stored_f = fold(stored).strip()
    if not extra_f:
        return stored_f
    if not stored_f:
        return extra_f
    extra_tokens = [token for token in extra_f.split() if token not in _CLARIFY_SKIP]
    if not extra_tokens:
        return stored_f

    def _unique(tokens: list[str]) -> str:
        seen: set[str] = set()
        out: list[str] = []
        for token in tokens:
            if token and token not in seen:
                seen.add(token)
                out.append(token)
        return " ".join(out)

    if is_position_only(" ".join(extra_tokens)):
        return _unique(stored_f.split() + extra_tokens)
    if all(token in _VARIANT_WORDS for token in extra_tokens):
        return _unique(stored_f.split() + extra_tokens)
    if all(token in _KIND_WORDS for token in extra_tokens):
        kept = [token for token in stored_f.split() if token not in _KIND_WORDS]
        return _unique(kept + extra_tokens)
    return extra_f


def catalog_search_query(query: str) -> str:
    """Término que entiende PartsLink24, no el de mostrador."""
    kind = pump_kind_wanted(query)
    if kind:
        return _SEARCH_PUMP.get(kind, fold(query))
    fkind = filter_kind_wanted(query)
    if fkind == "habitaculo":
        return "filtro habitaculo"
    if fkind:
        return f"filtro {fkind}"
    return fold(query)


def search_queries(query: str) -> list[str]:
    """Primero el término del catálogo; si no hay filas, el pedido original."""
    primary = catalog_search_query(query)
    folded = fold(query)
    out = [primary]
    if folded and folded not in out:
        out.append(folded)
    if pump_kind_wanted(query) == "agua":
        for alt in ("bomba liquido refrigerante", "bomba"):
            if alt not in out:
                out.append(alt)
    return out


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


def local_quote_ok(matches: list[dict], query: str = "") -> bool:
    """Hay un ítem rápido único: se cotiza en el local, sin PartsLink24."""
    if len(matches) != 1:
        return False
    if needs_chassis(matches):
        return False
    if not query.strip():
        return True
    item = matches[0]
    producto = fold(str(item.get("producto") or ""))
    name_words = [word for word in producto.split() if len(word) > 3]
    blob = fold(query)
    if name_words and not any(word in blob for word in name_words):
        return False
    modelo = fold(str(item.get("modelo") or ""))
    for token in re.findall(r"\b\d{3}\b", blob):
        if modelo and token not in modelo:
            return False
    return True


_HANGING = {
    "el",
    "la",
    "los",
    "las",
    "de",
    "del",
    "un",
    "una",
    "unos",
    "unas",
    "por",
    "para",
    "con",
    "que",
    "y",
    "o",
    "al",
    "lo",
    "se",
    "me",
    "te",
    "necesito",
    "preciso",
    "busco",
    "tenes",
    "tiene",
}

_LEAK_MARKERS = (
    "rules:",
    "system prompt",
    "system_instruction",
    "informacion interna",
    "hechos de esta consulta",
    "hechos (precios",
    "un vendedor humano entra solo",
    "no inventes codigos",
    "no inventes otros",
    "los hechos mandan",
    "asi contestamos consultas",
    "sos iahaf",
    "ai_system_prompt",
    "copia el tono",
    "copiá el tono",
)

SAFE_FALLBACK = (
    "Disculpá, se me cortó el mensaje. "
    "¿Me repetís la pieza y el auto? Si es compleja, pasame el chasis."
)


def is_sendable(text: str) -> bool:
    """False si Gemini cortó la frase o filtró instrucciones internas."""
    raw = (text or "").strip()
    if len(raw) < 8:
        return False
    blob = fold(raw)
    if raw.lower().lstrip().startswith("rules"):
        return False
    if any(fold(marker) in blob for marker in _LEAK_MARKERS):
        return False
    last = fold(re.sub(r"[^\wáéíóúñ]+$", "", raw.split()[-1], flags=re.IGNORECASE))
    if last in _HANGING:
        return False
    return True


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
