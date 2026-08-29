"""Expoyer: mayorista. Login por IDs fijos."""

from __future__ import annotations

import asyncio
import logging
import os
import re

from app.config import _ROOT, settings
from app.sales import catalog_close, fold

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_ROOT / ".playwright-browsers")

logger = logging.getLogger(__name__)

_STATE = _ROOT / "data" / "expoyer-state.json"
_LOCK = asyncio.Lock()
_PRICE = re.compile(r"\$\s*[\d\.]+")


def enabled() -> bool:
    return bool(
        settings.expoyer_enabled
        and settings.expoyer_user
        and settings.expoyer_password
    )


def format_rows(query: str, rows: list[dict]) -> str:
    if not rows:
        return ""
    lines = [f"En Expoyer para {query} aparece:"]
    for item in rows[:5]:
        piece = " — ".join(
            part for part in (item.get("code") or "", item.get("name") or "") if part
        )
        extra = item.get("price") or ""
        if extra:
            piece = f"{piece} ({extra})" if piece else extra
        if piece:
            lines.append(f"- {piece}")
    lines.append(catalog_close(len(rows)))
    return "\n".join(lines)


async def search_reply(query: str, model: str = "") -> str:
    if not enabled():
        return ""
    term = " ".join(part for part in (query, model) if part).strip()
    try:
        async with _LOCK:
            rows = await _search_locked(term)
    except Exception:
        logger.exception("Expoyer inesperado")
        return ""
    return format_rows(term, rows)


async def _search_locked(term: str) -> list[dict]:
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    context = None
    try:
        kwargs: dict = {"locale": "es-AR", "viewport": {"width": 1400, "height": 900}}
        if _STATE.exists():
            kwargs["storage_state"] = str(_STATE)
        context = await browser.new_context(**kwargs)
        page = await context.new_page()
        page.set_default_timeout(20000)
        await page.goto(settings.expoyer_base_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        login_btn = page.get_by_text("LOGIN", exact=False)
        if await login_btn.count() and await page.locator("#login-user").count() == 0:
            await login_btn.first.click()
            await page.wait_for_timeout(1200)
        if await page.locator("#login-user").count():
            await page.locator("#login-user").fill(settings.expoyer_user)
            await page.locator("#login-password").fill(settings.expoyer_password)
            btn = page.get_by_role("button", name=re.compile(r"ingresar", re.I))
            if await btn.count():
                await btn.first.click()
                await page.wait_for_timeout(4000)
        box = page.get_by_placeholder(re.compile(r"buscar|search|producto|codigo", re.I))
        if await box.count() == 0:
            box = page.locator("input[type='search']")
        if await box.count() == 0:
            logger.warning("Expoyer: no vi buscador (login o catálogo)")
            return []
        await box.first.fill(term)
        await box.first.press("Enter")
        await page.wait_for_timeout(4000)
        try:
            await context.storage_state(path=str(_STATE))
        except Exception:
            pass
        return await _read_rows(page)
    finally:
        if context:
            await context.close()
        await browser.close()
        await playwright.stop()


async def _read_rows(page) -> list[dict]:
    rows: list[dict] = []
    items = page.locator("tr, .product, .item, .card")
    n = min(await items.count(), 15)
    for i in range(n):
        raw = " ".join((await items.nth(i).inner_text()).split())
        if len(raw) < 8:
            continue
        blob = fold(raw)
        if "ingresar" in blob or "trayectoria" in blob:
            continue
        price = ""
        found = _PRICE.search(raw)
        if found:
            price = found.group(0)
        rows.append({"code": "", "name": raw[:80], "price": price})
        if len(rows) >= 5:
            break
    return rows
