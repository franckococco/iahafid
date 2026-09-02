"""Fichas del local. La IA no inventa: busca acá."""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from pathlib import Path

_DIR = Path(__file__).resolve().parent / "data"
_PATH = _DIR / "fichas.json"

_ALIASES = (
    ("gold trend", "gol trend"),
    ("amoriguador", "amortiguador"),
    ("amotiguador", "amortiguador"),
    ("casoleta", "cazoleta"),
    (" vw ", " volkswagen "),
)


def fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def load_all() -> list[dict]:
    if not _PATH.exists():
        return []
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    items = data.get("fichas") if isinstance(data, dict) else data
    return items if isinstance(items, list) else []


def save_all(items: list[dict]) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(
        json.dumps({"fichas": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def identity_key(ficha: dict) -> tuple[str, ...]:
    return tuple(
        fold(str(ficha.get(key) or ""))
        for key in ("marca", "modelo", "motor", "anio", "conjunto")
    )


def upsert(ficha: dict) -> dict:
    items = load_all()
    cleaned = _clean(ficha)
    fid = str(cleaned.get("id") or "").strip()
    if fid:
        for index, current in enumerate(items):
            if str(current.get("id")) == fid:
                cleaned["id"] = fid
                items[index] = cleaned
                save_all(items)
                return cleaned
    key = identity_key(cleaned)
    if any(key):
        for index, current in enumerate(items):
            if identity_key(current) == key:
                cleaned["id"] = str(current.get("id"))
                items[index] = cleaned
                save_all(items)
                return cleaned
    cleaned["id"] = fid or uuid.uuid4().hex[:10]
    items.append(cleaned)
    save_all(items)
    return cleaned


def delete(ficha_id: str) -> bool:
    items = load_all()
    kept = [item for item in items if str(item.get("id")) != ficha_id]
    if len(kept) == len(items):
        return False
    save_all(kept)
    return True


def find_for_query(query: str) -> tuple[dict | None, str]:
    """Devuelve la ficha que mejor pega, o None."""
    blob = _normalize_query(query)
    if not blob.strip():
        return None, "Vacío."
    ranked: list[tuple[int, dict]] = []
    for item in load_all():
        score = _score(blob, item)
        if score:
            ranked.append((score, item))
    ranked.sort(key=lambda row: row[0], reverse=True)
    if not load_all():
        return None, "No hay fichas cargadas."
    if not ranked or ranked[0][0] < 6:
        return None, "No hay ficha para ese auto o conjunto."
    return ranked[0][1], ""


def facts_text(ficha: dict, query: str = "") -> str:
    auto = " ".join(
        part
        for part in (
            ficha.get("marca"),
            ficha.get("modelo"),
            ficha.get("motor"),
            ficha.get("anio"),
        )
        if part
    )
    conjunto = str(ficha.get("conjunto") or "").strip()
    lines = [f"Auto: {auto or 'sin dato'}.", f"Conjunto: {conjunto or 'sin dato'}."]
    notas = str(ficha.get("notas") or "").strip()
    if notas:
        lines.append(f"Notas del local: {notas}")
    venta = str(ficha.get("venta") or "").strip()
    if venta:
        lines.append(f"Cómo vender (seguí esta idea, no inventes marcas): {venta}")
    piezas = ficha.get("piezas") or []
    asked = piezas_pedidas(query, ficha) if query else []
    if asked:
        names = ", ".join(str(p.get("nombre") or "") for p in asked)
        lines.append(f"El cliente pidió: {names}.")
        lines.append(
            "Confirmá esa pieza y preguntá si lleva las otras del conjunto "
            "(estilo: ¿amortiguador y bujes tenés?)."
        )
    if not piezas:
        lines.append("Piezas: todavía no hay ninguna cargada.")
    else:
        lines.append("Piezas de esta ficha (no inventes otras ni marcas que no estén acá):")
        for piece in piezas:
            nombre = str(piece.get("nombre") or "").strip()
            if not nombre:
                continue
            extra = " · ".join(
                part
                for part in (
                    piece.get("marca") or "",
                    piece.get("lado") or "",
                    piece.get("codigo") or "",
                    piece.get("nota") or "",
                )
                if str(part).strip()
            )
            lines.append(f"- {nombre}" + (f" ({extra})" if extra else ""))
    lines.append("Si falta un código, decí que se confirma en el local. No inventes.")
    return "\n".join(lines)


def piezas_pedidas(query: str, ficha: dict) -> list[dict]:
    blob = _normalize_query(query)
    hit: list[dict] = []
    for piece in ficha.get("piezas") or []:
        name = fold(str(piece.get("nombre") or ""))
        if not name:
            continue
        tokens = [tok for tok in re.split(r"\s+", name) if len(tok) > 3]
        key = tokens[0] if tokens else name
        if name in blob or (key and key in blob):
            hit.append(piece)
    return hit


def _normalize_query(query: str) -> str:
    blob = f" {fold(query)} "
    for old, new in _ALIASES:
        blob = blob.replace(old, new)
    return blob.strip()


def _clean(ficha: dict) -> dict:
    piezas = []
    for piece in ficha.get("piezas") or []:
        if not isinstance(piece, dict):
            continue
        nombre = str(piece.get("nombre") or "").strip()
        if not nombre:
            continue
        piezas.append(
            {
                "nombre": nombre[:80],
                "marca": str(piece.get("marca") or "").strip()[:40],
                "lado": str(piece.get("lado") or "").strip()[:40],
                "codigo": str(piece.get("codigo") or "").strip()[:40],
                "nota": str(piece.get("nota") or "").strip()[:120],
            }
        )
    return {
        "id": str(ficha.get("id") or "").strip(),
        "marca": str(ficha.get("marca") or "").strip()[:40],
        "modelo": str(ficha.get("modelo") or "").strip()[:40],
        "motor": str(ficha.get("motor") or "").strip()[:40],
        "anio": str(ficha.get("anio") or "").strip()[:12],
        "conjunto": str(ficha.get("conjunto") or "").strip()[:60],
        "notas": str(ficha.get("notas") or "").strip()[:400],
        "venta": str(ficha.get("venta") or "").strip()[:400],
        "piezas": piezas,
    }


def _score(blob: str, item: dict) -> int:
    score = 0
    for key, weight in (
        ("marca", 2),
        ("modelo", 4),
        ("motor", 3),
        ("anio", 2),
        ("conjunto", 4),
    ):
        value = fold(str(item.get(key) or ""))
        if not value:
            continue
        if value in blob:
            score += weight
            continue
        tokens = [tok for tok in re.split(r"\s+", value) if len(tok) > 2]
        if tokens and all(tok in blob for tok in tokens):
            score += weight
    for piece in item.get("piezas") or []:
        name = fold(str(piece.get("nombre") or ""))
        tokens = [tok for tok in re.split(r"\s+", name) if len(tok) > 3]
        key = tokens[0] if tokens else name
        if key and key in blob:
            score += 3
            break
    return score
