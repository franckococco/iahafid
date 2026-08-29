"""Elige catálogo: VW → PartsLink24; Peugeot/Citroën → Service Box + Infobal + Expoyer."""

from __future__ import annotations

import logging

from app import expoyer, infobal, partslink, servicebox
from app.sales import oem_family

logger = logging.getLogger(__name__)


def listed_has_parts(listed: str) -> bool:
    return partslink.listed_has_parts(listed) or infobal_or_expoyer_hit(listed)


def listed_unique_part(listed: str) -> bool:
    """True si el catálogo dejó un solo ítem: se manda el círculo y no se deriva."""
    if not listed_has_parts(listed):
        return False
    bullets = [
        line for line in (listed or "").splitlines() if line.strip().startswith("-")
    ]
    return len(bullets) == 1


def infobal_or_expoyer_hit(listed: str) -> bool:
    blob = (listed or "").lower()
    return "aparece:" in blob and (
        "infobal" in blob or "expoyer" in blob or "service box" in blob
    )


async def lookup_reply(
    chasis: str,
    query: str,
    screenshot_to: str | None = None,
    brand: str = "",
    model: str = "",
    spec: dict | None = None,
) -> str:
    family = oem_family(brand, model, chasis)
    logger.info("Catálogo %s marca=%s modelo=%s chasis=%s", family, brand, model, chasis)
    if family == "vw":
        return await partslink.lookup_reply(
            chasis,
            query,
            screenshot_to=screenshot_to,
            brand=brand or "volkswagen",
            model=model,
            spec=spec,
        )
    chunks: list[str] = []
    if infobal.enabled():
        text = await infobal.search_reply(query, model=model, brand=brand or "peugeot")
        if text:
            chunks.append(text)
    if not chunks and expoyer.enabled():
        text = await expoyer.search_reply(query, model=model)
        if text:
            chunks.append(text)
    if not chunks and chasis and servicebox.enabled():
        text = await servicebox.lookup_reply(chasis, query)
        if text:
            chunks.append(text)
    if chunks:
        return "\n".join(chunks)
    auto = " ".join(part for part in (brand, model) if part) or "ese auto"
    return (
        f"Anoté el chasis {chasis} ({auto}). "
        "No ubiqué esa pieza en el catálogo. Lo mira un vendedor."
    )
