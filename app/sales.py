"""Reglas de mostrador: cuándo cotizar, cuándo pedir chasis, cuándo pasar a un vendedor."""

from __future__ import annotations

import re
import unicodedata

HANDOFF_REPLY = (
    "Dale, te dejo con un compañero del local para esto. "
    "En un rato te escriben por acá."
)


def catalog_close(n_items: int) -> str:
    """Una pieza: código y precio en el local. Varias: no encargar, pasa a vendedor."""
    if n_items <= 1:
        return "Ese es el que corresponde. El precio te lo confirmamos en el local."
    return (
        "Hay varias en el catálogo; no te armo el encargo desde acá. "
        "Te dejo con un vendedor para que te marque la que corresponde."
    )

ASK_CHASSIS_REPLY = (
    "Pasame el chasis de la cédula o el parabrisas, no el de motor."
)

GOT_CHASSIS_ONLY = "Listo, anoté el chasis. ¿Qué pieza buscás?"

RESET_REPLY = "Dale, de cero. ¿Qué pieza y para qué auto?"

NEED_DETAILS = "¿Qué pieza necesitás y para qué auto?"

GREET_REPLY = (
    "Hola, ¿cómo andás? Acá en el local te ayudo con el repuesto. "
    "Cuando quieras decime la pieza y el auto."
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
    """Marca del auto para entrar al catálogo correcto (último auto nombrado gana)."""
    brand, _ = named_vehicle(*texts)
    return brand


def model_hint(*texts: str) -> str:
    """Modelo nombrado por el cliente (Amarok, 308, C3…)."""
    _, model = named_vehicle(*texts)
    return model


def oem_family(marca: str = "", modelo: str = "", chasis: str = "") -> str:
    """vw = PartsLink24; psa = Service Box, Infobal y Expoyer."""
    marca_f = fold(marca)
    modelo_f = fold(modelo)
    code = (chasis or "").strip().upper()
    if marca_f in {"peugeot", "citroen"}:
        return "psa"
    if marca_f in {"volkswagen"}:
        return "vw"
    if modelo_f in {
        "partner",
        "rifter",
        "berlingo",
        "207",
        "208",
        "308",
        "408",
        "301",
        "206",
        "307",
        "306",
        "205",
        "2008",
        "3008",
        "5008",
        "c3",
        "c4",
    }:
        return "psa"
    if code.startswith(("VF3", "VF7", "VF8")):
        return "psa"
    if code.startswith(_PREFIXES):
        return "vw"
    if 8 <= len(code) < 17:
        return "psa"
    return "vw"


def fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


# El último auto nombrado manda. Así "pastillas Amarok" no cotiza un C3 del catálogo de muestra.
_NAMED_MODELS: dict[str, tuple[str, str]] = {
    "amarok": ("volkswagen", "amarok"),
    "bora": ("volkswagen", "bora"),
    "golf": ("volkswagen", "golf"),
    "vento": ("volkswagen", "vento"),
    "fox": ("volkswagen", "fox"),
    "suran": ("volkswagen", "suran"),
    "saveiro": ("volkswagen", "saveiro"),
    "polo": ("volkswagen", "polo"),
    "passat": ("volkswagen", "passat"),
    "tiguan": ("volkswagen", "tiguan"),
    "taos": ("volkswagen", "taos"),
    "nivus": ("volkswagen", "nivus"),
    "virtus": ("volkswagen", "virtus"),
    "gol": ("volkswagen", "gol"),
    "c3": ("citroen", "c3"),
    "c4": ("citroen", "c4"),
    "c5": ("citroen", "c5"),
    "berlingo": ("citroen", "berlingo"),
    "5008": ("peugeot", "5008"),
    "3008": ("peugeot", "3008"),
    "2008": ("peugeot", "2008"),
    "partner": ("peugeot", "partner"),
    "rifter": ("peugeot", "rifter"),
    "408": ("peugeot", "408"),
    "308": ("peugeot", "308"),
    "301": ("peugeot", "301"),
    "208": ("peugeot", "208"),
    "207": ("peugeot", "207"),
    "206": ("peugeot", "206"),
    "307": ("peugeot", "307"),
    "306": ("peugeot", "306"),
    "205": ("peugeot", "205"),
    "108": ("peugeot", "108"),
    "107": ("peugeot", "107"),
    "106": ("peugeot", "106"),
}
_BRAND_ONLY = (
    (re.compile(r"\bvolkswagen\b"), "volkswagen"),
    (re.compile(r"\bvw\b"), "volkswagen"),
    (re.compile(r"\bpeugeou?t\b"), "peugeot"),
    (re.compile(r"\bcitroen\b"), "citroen"),
)


def _vehicle_in_blob(blob: str) -> tuple[str, str]:
    last_at = -1
    found = ("", "")
    for token, pair in _NAMED_MODELS.items():
        for match in re.finditer(rf"\b{re.escape(token)}\b", blob):
            if match.start() >= last_at:
                last_at = match.start()
                found = pair
    if found != ("", ""):
        return found
    last_at = -1
    brand = ""
    for regex, name in _BRAND_ONLY:
        for match in regex.finditer(blob):
            if match.start() >= last_at:
                last_at = match.start()
                brand = name
    return (brand, "") if brand else ("", "")


def named_vehicle(*texts: str) -> tuple[str, str]:
    """(marca, modelo) del último auto que nombró el cliente."""
    last = ("", "")
    for text in texts:
        got = _vehicle_in_blob(fold(text or ""))
        if got != ("", ""):
            last = got
    return last


def item_fits_vehicle(item: dict, brand: str = "", model: str = "") -> bool:
    """False si el SKU es de otro auto que el que pidió el cliente."""
    if not brand and not model:
        return True
    item_marca = fold(str(item.get("marca") or ""))
    item_modelo = fold(str(item.get("modelo") or ""))
    if brand:
        aliases = {brand, "vw"} if brand == "volkswagen" else {brand}
        if item_marca:
            if item_marca not in aliases and brand not in item_marca:
                return False
        elif not model:
            return False
    if model:
        if not item_modelo:
            return False
        if model not in item_modelo and item_modelo not in model:
            return False
    return True


def wants_human(text: str) -> bool:
    blob = fold(text)
    return any(phrase in blob for phrase in _HANDOFF)


def wants_reset(text: str) -> bool:
    blob = fold(text)
    if any(fold(phrase) in blob for phrase in _RESET):
        return True
    tokens = blob.split()
    if 1 <= len(tokens) <= 3 and tokens[0] == "nuevo":
        if any(tok.startswith(("pedi", "consul")) for tok in tokens[1:]):
            return True
    return False


def wants_photo(text: str) -> bool:
    blob = fold(text)
    return any(fold(phrase) in blob for phrase in _PHOTO)


_GREET_RE = re.compile(
    r"\b(hola+|holis|buenas|saludos|hey|"
    r"buen(as)?\s*(dias?|tardes?|noches?)|"
    r"que\s+tal|como\s+(estas|andas|va))\b",
    re.IGNORECASE,
)
_SMALL_TALK = {
    "hola",
    "holis",
    "holaa",
    "buenas",
    "buen",
    "dia",
    "dias",
    "tarde",
    "tardes",
    "noche",
    "noches",
    "saludos",
    "hey",
    "que",
    "tal",
    "como",
    "estas",
    "andas",
    "anda",
    "todo",
    "bien",
    "vos",
    "va",
    "che",
    "ey",
}


def is_greeting_only(text: str) -> bool:
    """True si solo saludó: no pieza, no chasis, no foto."""
    cleaned = re.sub(r"[^\wáéíóúñ\s]", " ", fold(text))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned or not _GREET_RE.search(cleaned):
        return False
    if wants_photo(text) or wants_human(text) or wants_reset(text):
        return False
    if extract_chassis(text):
        return False
    leftover = piece_query(cleaned)
    if not leftover:
        return True
    return all(token in _SMALL_TALK for token in leftover.split())


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
            if 8 <= len(code) <= 17 and (
                _looks_like_chassis(code) or code.isdigit()
            ):
                return code
    # Pegaron solo el código (8–17), típico cuando pedimos el chasis.
    if len(tokens) == 1:
        code = tokens[0].upper()
        if 8 <= len(code) <= 17 and _looks_like_chassis(code):
            return code
    # "8G535332 partner furgoneta": un solo código corto mezclado con el auto.
    shorts = [
        token.upper()
        for token in tokens
        if 8 <= len(token) <= 12 and _looks_like_chassis(token.upper())
    ]
    if len(shorts) == 1:
        return shorts[0]
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
            "Te dejo con un compañero para ubicar la pieza exacta. En un rato te escriben."
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
    "quiero",
    "busco",
    "buscar",
    "buscando",
    "pedi",
    "pediste",
    "pedir",
    "pidiendo",
    "pidio",
    "sale",
    "cuanto",
    "cuales",
    "productos",
    "stock",
    "foto",
    "imagen",
    "despiece",
    "mostrar",
    "mostrame",
    "muestrame",
    "muestra",
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
    "peugeout",
    "citroen",
    "volkswagen",
    "vw",
    "audi",
    "308",
    "207",
    "208",
    "206",
    "301",
    "306",
    "307",
    "408",
    "c3",
    "partner",
    "rifter",
    "berlingo",
    "furgoneta",
    "furgon",
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


def is_motor_clarify(query: str) -> bool:
    """El cliente solo aclaró cilindrada o nafta/diesel, no una pieza nueva."""
    hints = motor_hint(query)
    if not hints.get("litros") and not hints.get("fuel"):
        return False
    tokens = [
        token
        for token in fold(query).replace(",", ".").split()
        if token and token not in _HANGING
    ]
    motorish = {
        "nafta",
        "naftero",
        "diesel",
        "gasoil",
        "gasol",
        "hdi",
        "tdi",
        "1.4",
        "1.6",
        "motor",
        "cilindrada",
        "litros",
    }
    leftover = [
        token
        for token in tokens
        if token not in motorish and not re.fullmatch(r"1[.][46]", token)
    ]
    return not leftover


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


def motor_hint(*texts: str) -> dict:
    """1.4 / 1.6 y nafta / diesel, si el cliente lo dijo."""
    blob = fold(" ".join(t for t in texts if t)).replace(",", ".")
    litros = ""
    if re.search(r"\b1\s*[.]?\s*4\b", blob) or "1.4" in blob:
        litros = "1.4"
    if re.search(r"\b1\s*[.]?\s*6\b", blob) or "1.6" in blob:
        litros = "1.6"
    fuel = ""
    if any(word in blob for word in ("hdi", "diesel", "gasoil", "gasol")):
        fuel = "diesel"
    if any(word in blob for word in ("nafta", "naftero")):
        fuel = "nafta"
    return {"litros": litros, "fuel": fuel}


def peugeot_drill_spec(model: str, hints: dict) -> dict | None:
    """Arma la ficha para bajar el 207/208 en PartsLink si no está el chasis de 8."""
    model = (model or "").strip()
    litros = str(hints.get("litros") or "")
    fuel = str(hints.get("fuel") or "")
    if not model or not litros or not fuel:
        return None
    motor = ""
    motor_code = ""
    if model == "207" and litros == "1.4" and fuel == "nafta":
        motor, motor_code = "1.4 i 75", "TU3JP"
    elif model == "207" and litros == "1.4" and fuel == "diesel":
        motor, motor_code = "1.4 HDI 70", ""
    elif model == "207" and litros == "1.6" and fuel == "nafta":
        motor, motor_code = "1.6 i 16v 110", "TU5JP4"
    elif model == "207" and litros == "1.6" and fuel == "diesel":
        motor, motor_code = "1.6 HDI", ""
    elif litros == "1.4" and fuel == "nafta":
        motor, motor_code = "1.4 i 75", "TU3JP"
    elif litros == "1.6" and fuel == "nafta":
        motor, motor_code = "1.6 i 16v 110", "TU5JP4"
    if not motor:
        return None
    return {
        "marca": "peugeot",
        "modelo": model,
        "amlat": True,
        "carroceria": "BERLINA 5 PUERTAS",
        "motor": motor,
        "motor_code": motor_code,
        "caja": "CVM 5",
    }


def ask_motor_reply(modelo: str, hints: dict | None = None) -> str:
    """Chasis de 8 que no está en la lista: falta cilindrada y nafta/diesel."""
    hints = hints or {}
    litros = str(hints.get("litros") or "")
    fuel = str(hints.get("fuel") or "")
    if litros and not fuel:
        return f"Anoté el {modelo or 'auto'} {litros}. ¿Nafta o diesel?"
    if fuel and not litros:
        return f"Anoté {fuel}. ¿Es 1.4 o 1.6?"
    return f"Anoté el chasis. El {modelo or 'auto'} ¿es 1.4 o 1.6, nafta o diesel?"


def advice_hint(query: str) -> str:
    """Consejo de mostrador: no es código ni precio."""
    blob = fold(query)
    kind = pump_kind_wanted(query)
    if kind == "agua":
        return (
            "Consejo permitido: una frase, bomba de agua = refrigeración. "
            "Junta y líquido si hace falta. No inventes códigos ni precios."
        )
    if kind == "combustible":
        return (
            "Consejo permitido: es la bomba que manda combustible. "
            "No la mezcles con la de agua. No inventes códigos extra."
        )
    if kind == "aceite":
        return "Consejo permitido: es la bomba de aceite del motor. No inventes códigos extra."
    if "filtro" in blob and "aceite" in blob:
        return (
            "Consejo permitido: el filtro de aceite va en el service. "
            "No cotices aceite si no está en HECHOS."
        )
    if any(word in blob for word in ("amortiguador", "amort")):
        return (
            "Consejo permitido: los amortiguadores van por eje y a veces de a pares. "
            "No inventes el lado ni el código."
        )
    if any(word in blob for word in ("faro", "optica", "piloto")):
        return "Consejo permitido: el faro va izquierdo o derecho. Pedí el lado si falta."
    if "correa" in blob or "distribucion" in blob:
        return "Consejo permitido: distribución es trabajo fino; si hay duda, un compañero lo confirma."
    if "radiador" in blob:
        return (
            "Consejo permitido: una frase, el radiador enfría el motor. "
            "Refrigerante al cambiarlo. No inventes códigos ni precios."
        )
    if not blob:
        return ""
    return (
        "Consejo permitido: una frase para qué sirve. "
        "No inventes compatibilidad, códigos ni precios."
    )


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
        if is_motor_clarify(msg) or is_motor_clarify(piece_query(msg, chasis)):
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
    if extract_chassis(query) or "chasis" in fold(query):
        return False
    item = matches[0]
    brand, model = named_vehicle(query)
    if (brand or model) and not item_fits_vehicle(item, brand, model):
        return False
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
    "Disculpá, se me cortó. "
    "¿Me repetís la pieza y el auto? Si es de las finas, pasame el chasis."
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
    if last in _HANGING and not raw.endswith((".", "?", "!", "…")):
        return False
    if len(raw.split()) >= 5 and not raw.endswith((".", "?", "!", "…")):
        return False
    if blob.startswith(("hola", "holis", "buenas")) and "pieza" not in blob and "repuesto" not in blob:
        # Saludo suelto o "¡Hola! Para confirmarte…" a mitad de un pedido.
        if "apart" not in blob and "stock" not in blob and "chasis" not in blob:
            return False
    return True


def chassis_context(chasis: str) -> str:
    if not chasis:
        return (
            "El cliente todavía no dio número de chasis. "
            "Pedilo SOLO si la pieza es compleja o hay más de una opción. "
            "Nunca pidas número de motor. Nunca inventes un chasis."
        )
    return (
        f"El cliente ya dio el número de chasis: {chasis}. "
        "No lo vuelvas a pedir. Nunca pidas número de motor. "
        "Nunca inventes otro chasis. Solo usá este. "
        "Si la pieza es rápida, cotizá igual; el chasis queda anotado."
    )
