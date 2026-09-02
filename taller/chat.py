"""Consulta: primero la ficha, después Gemini solo redacta."""

from __future__ import annotations

from app.ai import reply_to
from app.config import settings
from taller.knowledge import facts_text, find_for_query, piezas_pedidas

_SYSTEM = (
    "Sos empleado de mostrador de una repuestera. "
    "Los HECHOS de la ficha mandan: copiá piezas, marcas y códigos tal cual. "
    "No inventes una pieza ni una marca (Sachs, Monroe, etc.) que no esté en HECHOS. "
    "Si el cliente pidió UNA pieza, confirmala y preguntá por las otras del conjunto, "
    "como: ¿amortiguador y bujes tenés? Si hay marca en la ficha, decí que esa le va bien a ESTE auto. "
    "No vomites el catálogo: primero lo que pidió, después el cruce. "
    "Si HECHOS dice que no hay ficha, decilo y pedí marca, modelo, año, motor o conjunto. "
    "Argentino informal, de vos, máximo 5 oraciones. No copies la palabra HECHOS."
)


async def answer(message: str, history: list[dict] | None = None) -> dict:
    ficha, miss = find_for_query(message)
    if ficha:
        facts = facts_text(ficha, message)
        fallback = _fallback_from_ficha(ficha, message)
    else:
        facts = (
            "No hay ficha para esta consulta. "
            f"{miss} "
            "No inventes piezas. Pedí que la carguen en el maquetado."
        )
        fallback = (
            "Ese auto o conjunto todavía no está en la base. "
            "Cargalo a la izquierda y preguntame de nuevo."
        )
    extra = f"{_SYSTEM}\n\nHECHOS:\n{facts}"
    if settings.ai_mode.strip().lower() == "echo":
        text = fallback
    else:
        text = await reply_to(message, history=history or [], extra_context=extra)
        if not text or text.startswith("Tuve un problema"):
            text = fallback
    return {"answer": text, "ficha": ficha, "hechos": facts}


def _label(piece: dict) -> str:
    name = str(piece.get("nombre") or "").strip()
    brand = str(piece.get("marca") or "").strip()
    return f"{name} {brand}".strip() if brand else name


def _fallback_from_ficha(ficha: dict, query: str = "") -> str:
    auto = " ".join(
        part
        for part in (ficha.get("marca"), ficha.get("modelo"), ficha.get("motor"), ficha.get("anio"))
        if part
    )
    conjunto = ficha.get("conjunto") or "ese conjunto"
    piezas = [
        piece
        for piece in (ficha.get("piezas") or [])
        if str(piece.get("nombre") or "").strip()
    ]
    if not piezas:
        return f"Tengo ficha de {auto} ({conjunto}), pero todavía no hay piezas cargadas."

    asked = piezas_pedidas(query, ficha)
    venta = str(ficha.get("venta") or "").strip()
    pares = " Van de a pares." if "par" in " ".join(
        str(p.get("lado") or "") for p in piezas
    ).lower() else ""

    if asked:
        asked_txt = ", ".join(_label(p) for p in asked)
        asked_names = {str(p.get("nombre") or "") for p in asked}
        others = [p for p in piezas if str(p.get("nombre") or "") not in asked_names]
        if others:
            offer = ", ".join(_label(p) for p in others)
            brands = [str(p.get("marca") or "").strip() for p in others if str(p.get("marca") or "").strip()]
            pitch = ""
            if brands:
                model = ficha.get("modelo") or "auto"
                pitch = f" Tenemos {brands[0]} que le va bien a este {model}."
            elif venta:
                pitch = f" {venta}"
            return f"Sí, {asked_txt} para el {auto}. ¿{offer} tenés?{pitch}{pares}"
        extra = f" {venta}" if venta else ""
        return f"Sí, {asked_txt} para el {auto}.{extra}{pares}"

    listed = ", ".join(_label(p) for p in piezas)
    extra = f" {venta}" if venta else ""
    return f"En {auto}, {conjunto}, le va: {listed}.{extra} El precio o el código fino te lo confirmamos en el local."
