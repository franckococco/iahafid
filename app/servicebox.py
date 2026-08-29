"""Service Box (Peugeot / Citroën OEM). Si el sitio está caído, devolvemos vacío."""

from __future__ import annotations

import asyncio
import logging
import os
import re

from app.config import _ROOT, settings

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_ROOT / ".playwright-browsers")

logger = logging.getLogger(__name__)

_STATE = _ROOT / "data" / "servicebox-state.json"
_LOCK = asyncio.Lock()


def enabled() -> bool:
    return bool(
        settings.servicebox_enabled
        and settings.servicebox_user
        and settings.servicebox_password
    )


async def lookup_reply(chasis: str, query: str) -> str:
    if not enabled() or not chasis:
        return ""
    try:
        async with _LOCK:
            return await _lookup_locked(chasis, query)
    except Exception:
        logger.exception("Service Box inesperado")
        return ""


async def _lookup_locked(chasis: str, query: str) -> str:
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
        await page.goto(settings.servicebox_base_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        body = await page.inner_text("body")
        if "problema técnico" in body.lower() or "technical problem" in body.lower():
            logger.warning("Service Box: sitio con problema técnico")
            return ""
        for label in ("Español (Argentina)", "Español", "English"):
            loc = page.get_by_text(label, exact=False)
            if await loc.count():
                try:
                    await loc.first.click(timeout=5000)
                    await page.wait_for_timeout(1500)
                    break
                except Exception:
                    continue
        user = page.locator("#username, input[name='username']")
        pwd = page.locator("#password, input[name='password'], input[type='password']")
        if await user.count() and await pwd.count():
            await user.first.fill(settings.servicebox_user)
            await pwd.first.fill(settings.servicebox_password)
            btn = page.locator("#btsubmit, button[type=submit], input[type=submit]")
            if await btn.count():
                await btn.first.click()
                await page.wait_for_timeout(4000)
        vin = page.get_by_placeholder(re.compile(r"vin|vis|chasis|chassis", re.I))
        if await vin.count() == 0:
            vin = page.locator("input[name*='vin' i], input[id*='vin' i]")
        if await vin.count() == 0:
            logger.warning("Service Box: no vi el campo VIN")
            return ""
        await vin.first.fill(chasis)
        ok = page.get_by_role("button", name=re.compile(r"^ok$|buscar", re.I))
        if await ok.count():
            await ok.first.click()
        await page.wait_for_timeout(3500)
        box = page.get_by_placeholder(re.compile(r"pieza|part|recherch", re.I))
        if await box.count() and query:
            await box.first.fill(query)
            await box.first.press("Enter")
            await page.wait_for_timeout(3500)
        try:
            await context.storage_state(path=str(_STATE))
        except Exception:
            pass
        text = " ".join((await page.inner_text("body")).split())[:500]
        if not text or "problema técnico" in text.lower():
            return ""
        return ""
    finally:
        if context:
            await context.close()
        await browser.close()
        await playwright.stop()
