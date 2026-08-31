"""Guarda cómo contestamos consultas que se repiten. Gemini toma el tono; los hechos los pone el software."""

from __future__ import annotations

import json
import logging
import re
import threading

from app.catalog import _LEARNED, _save_json, _tokens
from app.sales import fold, is_sendable, daypart

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_MAX = 120
_OEM = re.compile(
    r"\b[A-Z0-9]{2,3}\s[A-Z0-9]{3}\s[A-Z0-9]{3}(?:\s[A-Z0-9])?\b",
    re.IGNORECASE,
)

_SEEDS = (
    {
        "kind": "quote",
        "keys": ["filtro", "aceite", "308"],
        "user": "tenes filtro para el 308 2014",
        "assistant": (
            "Sí, el filtro de aceite del 308 2012-2018 lo tengo a $12.500 y hay 8. "
            "¿Te lo aparto?"
        ),
    },
    {
        "kind": "chassis",
        "keys": ["faro", "trasero"],
        "user": "necesito el faro derecho trasero",
        "assistant": (
            "Para el faro preciso el número de chasis, el de la cédula o el parabrisas. "
            "El del motor no me sirve. ¿Me lo pasás y te lo ubico?"
        ),
    },
    {
        "kind": "oem",
        "keys": ["faro", "trasero"],
        "user": "faro derecho trasero",
        "assistant": (
            "Con ese chasis el faro trasero derecho aparece como 2H1 945 096 H. "
            "Ese es el que corresponde. El precio te lo confirmamos en el local."
        ),
    },
    {
        "kind": "got_chassis",
        "keys": ["chasis"],
        "user": "8AWDD22H6JA023887",
        "assistant": "Listo, anoté el chasis. Decime qué pieza estás buscando y te la ubico.",
    },
)


def similar_replies(query: str, kind: str, limit: int = 3) -> str:
    """Few-shot de consultas parecidas, para que Gemini no suene siempre igual de plantilla."""
    keys = set(_tokens(query))
    ranked: list[tuple[int, dict]] = []
    for item in _all_replies():
        if kind and item.get("kind") != kind:
            continue
        saved = set(item.get("keys") or [])
        score = len(keys & saved)
        if item.get("seed"):
            score += 1
        score += min(int(item.get("hits") or 0), 4)
        if score:
            ranked.append((score, item))
    ranked.sort(key=lambda row: row[0], reverse=True)
    picked = [item for _, item in ranked[:limit]]
    if not picked:
        return ""
    lines = [
        "Así contestamos consultas parecidas (copiá el tono, no el texto literal; "
        "los códigos y precios de los HECHOS de ahora mandan):"
    ]
    for item in picked:
        reply = str(item.get("assistant") or "").strip()
        if reply and is_sendable(reply):
            lines.append(f"- {reply}")
    if len(lines) < 2:
        return ""
    return "\n".join(lines)


def remember_reply(kind: str, query: str, answer: str) -> None:
    text = (answer or "").strip()
    if not kind or len(text) < 20 or len(text) > 900:
        return
    blob = fold(text)
    if "problema para generar" in blob or "iahaf recibio" in blob:
        return
    if "se me corto" in blob:
        return
    if text[-1:] not in ".?!":
        return
    if not is_sendable(text):
        return
    keys = _tokens(query)[:8]
    if len(keys) < 1:
        return
    with _LOCK:
        data = _load()
        replies = data.setdefault("replies", [])
        for item in replies:
            if item.get("kind") == kind and item.get("keys") == keys:
                item["assistant"] = text
                item["hits"] = int(item.get("hits") or 0) + 1
                item.pop("seed", None)
                _save_json(_LEARNED, data)
                return
        replies.append(
            {
                "kind": kind,
                "keys": keys,
                "user": " ".join(keys),
                "assistant": text,
                "hits": 1,
            }
        )
        data["replies"] = replies[-_MAX:]
        _save_json(_LEARNED, data)
        logger.info("Aprendí tono %s %r", kind, " ".join(keys))


def remember_ask(user: str, pieza: str, found: bool, chasis: str = "") -> None:
    """Inbox de cómo pide la gente, encontrado o no. Gemini no inventa con esto."""
    keys = _tokens(pieza or user)[:8]
    if not keys:
        return
    with _LOCK:
        data = _load()
        asks = data.setdefault("asks", [])
        folded = fold(" ".join(keys))
        for item in asks:
            if fold(" ".join(item.get("keys") or [])) == folded:
                item["hits"] = int(item.get("hits") or 0) + 1
                item["found"] = bool(found) or bool(item.get("found"))
                item["last"] = (user or "")[:200]
                if chasis:
                    item["chasis"] = chasis
                _save_json(_LEARNED, data)
                return
        asks.append(
            {
                "keys": keys,
                "pieza": pieza,
                "last": (user or "")[:200],
                "chasis": chasis,
                "found": found,
                "hits": 1,
            }
        )
        data["asks"] = asks[-_MAX:]
        _save_json(_LEARNED, data)
        logger.info("Anoté pedido %r found=%s", " ".join(keys), found)


def list_asks(limit: int = 40) -> list[dict]:
    asks = list(_load().get("asks") or [])
    asks.reverse()
    return asks[:limit]


def keeps_oem_codes(answer: str, facts: str) -> bool:
    codes = _OEM.findall(facts or "")
    if not codes:
        return True
    compact = re.sub(r"\s+", "", answer or "").upper()
    for code in codes[:4]:
        if re.sub(r"\s+", "", code).upper() not in compact:
            return False
    return True


def _all_replies() -> list[dict]:
    stored = list(_load().get("replies") or [])
    seeds = [{**seed, "seed": True, "hits": 0} for seed in _SEEDS]
    return stored + seeds


def _load() -> dict:
    if not _LEARNED.exists():
        return {"phrases": {}, "replies": [], "asks": []}
    try:
        data = json.loads(_LEARNED.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("learned.json inválido")
        return {"phrases": {}, "replies": [], "asks": []}
    if not isinstance(data, dict):
        return {"phrases": {}, "replies": [], "asks": []}
    data.setdefault("phrases", {})
    data.setdefault("replies", [])
    data.setdefault("asks", [])
    return data
