import json
import logging
import re
import threading
from pathlib import Path

from app.config import _ROOT
from app.sales import fold

logger = logging.getLogger(__name__)

_PRODUCTS = _ROOT / "data" / "products.json"
_LEARNED = _ROOT / "data" / "learned.json"
_MANUALS = _ROOT / "data" / "manuals"
_YEAR = re.compile(r"^\d{4}$")
_RANGE = re.compile(r"(\d{4})\s*[-–a]\s*(\d{4})")
_LOCK = threading.Lock()

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
    "cuanto",
    "sale",
    "precio",
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


def load_products() -> list[dict]:
    if not _PRODUCTS.exists():
        return []
    try:
        items = json.loads(_PRODUCTS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("products.json inválido")
        return []
    return items if isinstance(items, list) else []


def upsert_product(item: dict) -> dict:
    """Graba o actualiza un producto en el catálogo. Eso es lo que el bot consulta."""
    sku = str(item.get("sku") or "").strip()
    if not sku:
        raise ValueError("El producto necesita sku")
    with _LOCK:
        items = load_products()
        updated = dict(item)
        updated["sku"] = sku
        updated.setdefault("tipo", "rapido")
        for index, current in enumerate(items):
            if str(current.get("sku")) == sku:
                merged = dict(current)
                merged.update(updated)
                items[index] = merged
                _save_json(_PRODUCTS, items)
                return merged
        items.append(updated)
        _save_json(_PRODUCTS, items)
        return updated


def find_products(query: str, limit: int = 8) -> list[dict]:
    items = load_products()
    tokens = _tokens(query)
    if not tokens:
        return []
    learned_sku = _sku_from_learned(tokens)
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
        if learned_sku and str(item.get("sku")) == learned_sku:
            score += 5
        scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored][:limit]


def remember_match(query: str, matches: list[dict]) -> None:
    """Si la consulta cerró en un solo producto, guarda cómo lo pidió el cliente."""
    if len(matches) != 1:
        return
    item = matches[0]
    sku = str(item.get("sku") or "")
    tokens = _tokens(query)
    blob = fold(" ".join(str(v) for v in item.values()))
    useful = [
        token
        for token in tokens
        if _YEAR.match(token)
        or token in blob
        or _ALIASES.get(token, token) in blob
    ]
    if not sku or len(useful) < 2:
        return
    phrase = " ".join(useful)
    with _LOCK:
        data = _load_learned()
        phrases = data.setdefault("phrases", {})
        previous = phrases.get(phrase)
        if previous and previous.get("sku") != sku:
            return
        phrases[phrase] = {
            "sku": sku,
            "hits": int((previous or {}).get("hits") or 0) + 1,
        }
        _save_json(_LEARNED, data)
        logger.info("Aprendí consulta %r → %s", phrase, sku)


def is_complex(item: dict) -> bool:
    return fold(str(item.get("tipo") or "rapido")) == "complejo"


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
    if not matches or is_complex(matches[0]):
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
    tipo = item.get("tipo") or "rapido"
    extra = (
        "Pasá a un vendedor, no cierres vos."
        if is_complex(item)
        else "Podés cotizar y ofrecer apartar."
    )
    return (
        f"- {item.get('producto')} | {item.get('marca')} {item.get('modelo')} "
        f"({item.get('anio')}) | SKU {item.get('sku')} | "
        f"${item.get('precio')} | stock {item.get('stock')} | "
        f"tipo {tipo} | {item.get('notas', '')} | {extra}"
    )


def _tokens(query: str) -> list[str]:
    raw = fold(query).replace(",", " ").replace("?", " ").replace("!", " ")
    return [t for t in raw.split() if len(t) > 1 and t not in _STOP]


def _sku_from_learned(tokens: list[str]) -> str | None:
    if not tokens:
        return None
    phrase = " ".join(tokens)
    phrases = _load_learned().get("phrases") or {}
    if phrase in phrases:
        return str(phrases[phrase].get("sku") or "") or None
    hits = [
        info
        for saved, info in phrases.items()
        if saved and (saved in phrase or phrase in saved)
    ]
    if len(hits) == 1:
        return str(hits[0].get("sku") or "") or None
    return None


def _load_learned() -> dict:
    if not _LEARNED.exists():
        return {"phrases": {}}
    try:
        data = json.loads(_LEARNED.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("learned.json inválido")
        return {"phrases": {}}
    if not isinstance(data, dict):
        return {"phrases": {}}
    data.setdefault("phrases", {})
    return data


def _save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
