"""Prueba login de Infobal, Expoyer y Service Box. No imprime claves."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

os.environ.setdefault(
    "PLAYWRIGHT_BROWSERS_PATH",
    str(Path(__file__).resolve().parent.parent / ".playwright-browsers"),
)

from app.config import _ROOT, settings  # noqa: E402


async def _shot(page, name: str) -> None:
    path = _ROOT / "data" / f"probe-{name}.png"
    await page.screenshot(path=str(path), full_page=True)
    print(f"captura {name}: {path.name} url={page.url[:80]}")


async def probe_infobal(page) -> None:
    print("=== Infobal ===")
    await page.goto(settings.infobal_base_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
    user = page.locator("input[type='text'], input[name*='user' i], input[id*='user' i]").locator("visible=true")
    pwd = page.locator("input[type='password']").locator("visible=true")
    print("user boxes", await user.count(), "pwd", await pwd.count())
    if await user.count() and await pwd.count():
        await user.first.fill(settings.infobal_user)
        await pwd.first.fill(settings.infobal_password)
        btn = page.get_by_role("button", name=re.compile(r"acceder|ingresar|login", re.I))
        if await btn.count() == 0:
            btn = page.locator("button, input[type=submit]").locator("visible=true")
        await btn.first.click()
        await page.wait_for_timeout(4000)
    print("después login:", page.url[:100], "texto", (await page.inner_text("body"))[:180].replace("\n", " "))
    await _shot(page, "infobal")


async def probe_expoyer(page) -> None:
    print("=== Expoyer ===")
    await page.goto(settings.expoyer_base_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    user = page.get_by_label(re.compile(r"usuario", re.I))
    if await user.count() == 0:
        user = page.locator("input[type='text'], input[name*='user' i]").locator("visible=true")
    pwd = page.locator("input[type='password']").locator("visible=true")
    print("user boxes", await user.count(), "pwd", await pwd.count())
    if await user.count() and await pwd.count():
        await user.first.fill(settings.expoyer_user)
        await pwd.first.fill(settings.expoyer_password)
        btn = page.get_by_role("button", name=re.compile(r"ingresar|login|acceder", re.I))
        if await btn.count() == 0:
            btn = page.locator("button, input[type=submit]").locator("visible=true")
        await btn.first.click()
        await page.wait_for_timeout(4000)
    print("después login:", page.url[:100], "texto", (await page.inner_text("body"))[:180].replace("\n", " "))
    await _shot(page, "expoyer")


async def probe_servicebox(page) -> None:
    print("=== Service Box ===")
    await page.goto(settings.servicebox_base_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)
    # Prefer Español Argentina if visible
    es = page.get_by_text(re.compile(r"Español \(Argentina\)", re.I))
    if await es.count():
        await es.first.click()
        await page.wait_for_timeout(1500)
    user = page.locator("#username, input[name='username']").locator("visible=true")
    pwd = page.locator("#password, input[name='password'], input[type='password']").locator("visible=true")
    print("user boxes", await user.count(), "pwd", await pwd.count(), "url", page.url[:90])
    if await user.count() and await pwd.count():
        await user.first.fill(settings.servicebox_user)
        await pwd.first.fill(settings.servicebox_password)
        btn = page.locator("#btsubmit, #conx-btn, button[type=submit]").locator("visible=true")
        if await btn.count() == 0:
            btn = page.get_by_role("button").locator("visible=true")
        await btn.first.click()
        await page.wait_for_timeout(5000)
    print("después login:", page.url[:100], "texto", (await page.inner_text("body"))[:180].replace("\n", " "))
    await _shot(page, "servicebox")


async def main() -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(locale="es-AR", viewport={"width": 1280, "height": 900})
        try:
            await probe_infobal(page)
            await probe_expoyer(page)
            await probe_servicebox(page)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
