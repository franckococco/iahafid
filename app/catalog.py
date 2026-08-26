import json
import logging
import re
from pathlib import Path

from app.config import _ROOT
from app.sales import fold

logger = logging.getLogger(__name__)

_PRODUCTS = _ROOT / "data" / "products.json"
_MANUALS = _ROOT / "data" / "manuals"
_YEAR = re.compile(r"^\d{4}$")
_RANGE = re.compile(r"(\d{4})\s*[-–a]\s*(\d{4})")

# Palabras del cliente que no sirven para rankear.
_STOP = {
    "hola",
    "buenas",
    "buen",
    "dia",
    "dias",
    "tardes",
    "noches",
    "tenes",
    "tene",
    "tiene",
    "tienen",
    "hay",
    "para",
    "por",
    "una",
    "uno",
    "unos",
    "unas",
    "el",
    "la",
    "los",
    "las",
    "de",
    "del",
    "al",
    "un",
    "me",
    "te",
    "se",
    "che",
    "gracias",
    "porfa",
    "porfis",
    "queria",
    "necesito",
    "busco",
    "anda",
    "andaria",
}

# Cómo habla la gente vs. cómo está el catálogo.
_ALIASES = {
    "vw": "volkswagen",
    "v w": "volkswagen",
    "peu": "peugeot",
    "peuge": "peugeot",
    "citroen": "citroen",
    "filtro": "filtro",
    "filtros": "filtro",
    "aceite": "aceite",
    "pastilla": "pastillas",
    "pastillas": "pastillas",
    "freno": "freno",
    "frenos": "freno",
    "distribucion": "distribucion",
    "kit": "kit",
    "correa": "correa",
    "gol": "gol",
}


def find_products(query: str, limit: int = 8) -> list[dict]:
    if not _PRODUCTS.exists():
        return []
    try:
        items = json.loads(_PRODUCTS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("products.json inválido")
        return []

    tokens = _tokens(query)
    scored: list[tuple[int, dict]] = []
    for item in items:
        blob = fold(" ".join(str(v) for v in item.values()))
        score = 0
        for token in tokens:
            alias = _ALIASES.get(token, token)
            if _YEAR.match(token):
                continue
            if alias in blob or token in blob:
                score += 1
        if not score:
            continue
        anio = str(item.get("anio") or "")
        for token in tokens:
            if _YEAR.match(token) and _year_in_range(int(token), anio):
                score += 2
        scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored][:limit]


def search_products(query: str, limit: int = 8) -> str:
    matches = find_products(query, limit)
    if not matches:
        return (
            "No hay coincidencias en el catálogo para esta consulta. "
            "No inventes precios ni stock. Si el cliente ya dio marca y modelo "
            "y hay un ítem parecido, usalo. Si no, pedí SOLO el dato que falte "
            "(marca, modelo, año o pieza), uno por vez. "
            "Si ya está completo y no hay match, ofrecé pasarlo a un vendedor."
        )
    lines = [_product_line(item) for item in matches]
    return (
        "Productos encontrados (cotizá con estos datos; un año dentro del rango cuenta):\n"
        + "\n".join(lines)
    )


def fallback_quote(query: str) -> str | None:
    """Cotización de mostrador si Gemini falla. No inventa: usa el mejor match."""
    matches = find_products(query, limit=3)
    if not matches:
        return None
    item = matches[0]
    producto = item.get("producto") or "repuesto"
    marca = item.get("marca") or ""
    modelo = item.get("modelo") or ""
    anio = item.get("anio") or ""
    stock = item.get("stock")
    return (
        f"Sí, tengo {producto} para {marca} {modelo} ({anio}) a {_ars(item.get('precio'))}. "
        f"Hay {stock} en stock. ¿Lo apartás?"
    )


def _product_line(item: dict) -> str:
    return (
        f"- {item.get('producto')} | {item.get('marca')} {item.get('modelo')} "
        f"({item.get('anio')}) | SKU {item.get('sku')} | "
        f"${item.get('precio')} | stock {item.get('stock')} | {item.get('notas', '')}"
    )


def _tokens(query: str) -> list[str]:
    raw = fold(query).replace(",", " ").replace("?", " ").replace("!", " ")
    return [t for t in raw.split() if len(t) > 1 and t not in _STOP]


def _ars(value) -> str:
    try:
        return f"${int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(value)


def _year_in_range(year: int, anio_field: str) -> bool:
    match = _RANGE.search(anio_field)
    if match:
        return int(match.group(1)) <= year <= int(match.group(2))
    return str(year) in anio_field


def search_manuals(query: str, limit: int = 3) -> str:
    if not _MANUALS.exists():
        return "No hay manuales cargados todavía."
    files = [
        path
        for path in _MANUALS.iterdir()
        if path.is_file() and path.suffix.lower() in {".txt", ".md"}
    ]
    if not files:
        return "No hay manuales en texto todavía. Los PDF se van a poder cargar después."
    tokens = [t for t in _tokens(query) if len(t) > 2]
    hits: list[tuple[int, Path, str]] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        blob = fold(path.stem + " " + text)
        score = sum(1 for t in tokens if t in blob)
        if score:
            snippet = text.strip().replace("\n", " ")[:700]
            hits.append((score, path, snippet))
    hits.sort(key=lambda row: row[0], reverse=True)
    if not hits:
        return "No encontré un manual que coincida con esa consulta."
    parts = []
    for _, path, snippet in hits[:limit]:
        parts.append(f"Manual {path.name}: {snippet}")
    return "\n\n".join(parts)
