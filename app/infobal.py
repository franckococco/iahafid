"""Infobal / Bálsamo: stock y precio mayorista. Gemini no busca."""

from __future__ import annotations

import asyncio
import logging
import re

from app.browser import chromium_launch_kwargs
from app.config import _ROOT, settings
from app.sales import catalog_close, fold

logger = logging.getLogger(__name__)

_STATE = _ROOT / "data" / "infobal-state.json"
_LOCK = asyncio.Lock()
_PRICE = re.compile(r"\$\s*[\d\.]+(?:,\d{2})?")


class InfobalError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(
        settings.infobal_enabled
        and settings.infobal_user
        and settings.infobal_password
    )


def format_rows(query: str, rows: list[dict]) -> str:
    if not rows:
        return ""
    lines = [f"En Infobal para {query} aparece:"]
    for item in rows[:5]:
        piece = " — ".join(
            part for part in (item.get("code") or "", item.get("name") or "") if part
        )
        extra = item.get("price") or item.get("note") or ""
        if extra:
            piece = f"{piece} ({extra})" if piece else extra
        if piece:
            lines.append(f"- {piece}")
    lines.append(catalog_close(len(rows)))
    return "\n".join(lines)


async def search_reply(query: str, model: str = "", brand: str = "") -> str:
    if not enabled():
        return ""
    term = " ".join(part for part in (query, model, brand) if part).strip()
    try:
        async with _LOCK:
            rows = await _search_locked(query, model, brand)
    except Exception:
        logger.exception("Infobal inesperado")
        return ""
    return format_rows(term or query, _relevant_rows(rows, query, model, brand))


def _relevant_rows(rows: list[dict], query: str, model: str, brand: str) -> list[dict]:
    """No devolver radiador de aceite de otra marca si pidieron radiador de motor."""
    q = fold(query)
    model_f = fold(model)
    brand_f = fold(brand)
    want_oil = "aceite" in q
    kept: list[dict] = []
    for item in rows:
        name = fold(item.get("name") or "")
        if "radiador" in q and not want_oil and "aceite" in name:
            continue
        if model_f and model_f not in name:
            continue
        if brand_f and not model_f and brand_f not in name:
            continue
        kept.append(item)
    return kept


async def _search_locked(query: str, model: str, brand: str) -> list[dict]:
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(**chromium_launch_kwargs())
    context = None
    try:
        kwargs: dict = {"locale": "es-AR", "viewport": {"width": 1400, "height": 900}}
        if _STATE.exists():
            kwargs["storage_state"] = str(_STATE)
        context = await browser.new_context(**kwargs)
        page = await context.new_page()
        page.set_default_timeout(25000)
        await _ensure_login(page)
        terms = []
        for item in (query, f"{query} {model}".strip(), f"{query} {brand}".strip()):
            if item and item not in terms:
                terms.append(item)
        leftover: list[dict] = []
        rows: list[dict] = []
        for term in terms:
            found = await _run_search(page, term)
            if model:
                matched = [
                    item
                    for item in found
                    if fold(model) in fold(item.get("name") or "")
                ]
                if matched:
                    rows = matched
                    break
                if found:
                    leftover = found
            elif found:
                rows = found
                break
        if not rows:
            await _run_search(page, query)
            await _filter_brand(page, brand or "peugeot")
            await page.wait_for_timeout(2000)
            if model:
                await _filter_model(page, model)
                await page.wait_for_timeout(2000)
            rows = await _read_rows(page)
            if model:
                matched = [
                    item
                    for item in rows
                    if fold(model) in fold(item.get("name") or "")
                ]
                if matched:
                    rows = matched
                elif leftover:
                    rows = []
        try:
            await context.storage_state(path=str(_STATE))
        except Exception:
            pass
        return rows
    finally:
        if context:
            await context.close()
        await browser.close()
        await playwright.stop()


async def _ensure_login(page) -> None:
    await page.goto(settings.infobal_base_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(1200)
    if await page.locator("#nav_id").count():
        logger.info("Infobal: sesión vigente")
        return
    user = page.locator("input[type='text'], input[name*='user' i]").locator("visible=true")
    pwd = page.locator("input[type='password']").locator("visible=true")
    if await user.count() == 0 or await pwd.count() == 0:
        raise InfobalError("No vi el login de Infobal")
    await user.first.fill(settings.infobal_user)
    await pwd.first.fill(settings.infobal_password)
    btn = page.get_by_role("button", name=re.compile(r"acceder|ingresar|login", re.I))
    if await btn.count() == 0:
        btn = page.locator("button, input[type=submit]").locator("visible=true")
    await btn.first.click()
    await page.locator("#nav_id").wait_for(state="visible", timeout=20000)
    logger.info("Infobal: sesión iniciada")


async def _run_search(page, term: str) -> list[dict]:
    box = page.locator("#nav_id")
    await box.click()
    await box.fill("")
    await box.fill(term)
    await box.press("Enter")
    await page.wait_for_timeout(4000)
    body = fold(await page.inner_text("body"))
    if "no se ha encontrado ningun articulo" in body:
        logger.info("Infobal: sin artículos para %s", term)
        return []
    return await _read_rows(page)


async def _filter_brand(page, brand: str) -> None:
    ver = page.get_by_text("Ver todo", exact=False)
    if await ver.count():
        await ver.first.click()
        await page.wait_for_timeout(800)
    loc = page.get_by_text(re.compile(rf"^{re.escape(brand)}$", re.I))
    if await loc.count() == 0:
        loc = page.get_by_text(re.compile(re.escape(brand), re.I))
    if await loc.count():
        await loc.first.click()


async def _filter_model(page, model: str) -> None:
    loc = page.get_by_text(re.compile(re.escape(model), re.I))
    if await loc.count() == 0:
        ver = page.get_by_text("Ver todo", exact=False)
        if await ver.count() >= 2:
            await ver.nth(1).click()
            await page.wait_for_timeout(800)
        loc = page.get_by_text(re.compile(re.escape(model), re.I))
    if await loc.count():
        await loc.first.click()


async def _read_rows(page) -> list[dict]:
    rows: list[dict] = []
    trs = page.locator("table.t-Report-report tbody tr, tr.selected-row")
    n = min(await trs.count(), 12)
    for i in range(n):
        parsed = _parse_card((await trs.nth(i).inner_text()).strip())
        if parsed:
            rows.append(parsed)
    if rows:
        return rows
    cards = page.locator(".t-Card, .a-CardView-item")
    n = min(await cards.count(), 12)
    for i in range(n):
        parsed = _parse_card((await cards.nth(i).inner_text()).strip())
        if parsed:
            rows.append(parsed)
    return rows


_SKIP = (
    "vista",
    "grilla",
    "tarjetas",
    "ver todo",
    "ver mas",
    "ver menos",
    "modelos",
    "lineas",
    "motores",
    "novedades",
    "carrito",
    "informes",
    "ajustes",
    "mantener filtros",
    "volkswagen",
    "nissan",
    "renault",
    "varios",
    "peugeot",
    "citroen",
)


def _parse_card(text: str) -> dict:
    raw = " ".join(text.split())
    if len(raw) < 6:
        return {}
    blob = fold(raw)
    if any(skip in blob for skip in _SKIP):
        if not _PRICE.search(raw):
            return {}
    if "no se ha encontrado" in blob:
        return {}
    price = ""
    found = _PRICE.search(raw)
    if found:
        price = found.group(0)
    code = ""
    first = raw.split()[0] if raw.split() else ""
    if re.fullmatch(r"[A-Z0-9]{3,12}", first, re.I):
        code = first.upper()
    if not price and not code:
        return {}
    name = raw
    if "P. Venta" in raw:
        name = raw.split("P. Venta")[0].strip(" -")
    elif price:
        name = raw.replace(price, "").strip(" -")
    if code and name.upper().startswith(code):
        name = name[len(code) :].strip(" -")
    if fold(name) in _SKIP:
        return {}
    return {"code": code, "name": (name or code)[:80], "price": price}
