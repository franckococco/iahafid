"""Sigue Infobal (término radiador + filtro) y login Expoyer por IDs."""

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


async def shot(page, name: str) -> None:
    await page.screenshot(path=str(_ROOT / "data" / f"probe-{name}.png"), full_page=False)
    print(name, page.url[:90], (await page.inner_text("body"))[:280].replace("\n", " | "))


async def infobal(page) -> None:
    await page.goto(settings.infobal_base_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(1200)
    await page.locator("input[type='text']").first.fill(settings.infobal_user)
    await page.locator("input[type='password']").first.fill(settings.infobal_password)
    await page.locator("button, input[type=submit]").locator("visible=true").first.click()
    await page.wait_for_timeout(4000)
    box = page.locator("#nav_id")
    await box.fill("radiador")
    await box.press("Enter")
    await page.wait_for_timeout(5000)
    await shot(page, "infobal-rad")
    # abrir líneas
    ver = page.get_by_text("Ver todo", exact=False)
    print("ver todo count", await ver.count())
    if await ver.count():
        await ver.first.click()
        await page.wait_for_timeout(1500)
        await shot(page, "infobal-lineas")
    peug = page.get_by_text(re.compile(r"peugeot", re.I))
    print("peugeot locators", await peug.count())
    if await peug.count():
        await peug.first.click()
        await page.wait_for_timeout(2500)
        await shot(page, "infobal-peugeot")
    cards = page.locator(".t-Card, .a-CardView-item, tr a, .t-Report-cell")
    print("cards/cells", await cards.count())
    if await cards.count():
        texts = []
        for i in range(min(8, await cards.count())):
            texts.append((await cards.nth(i).inner_text())[:80].replace("\n", " "))
        print("sample", texts)


async def expoyer(page) -> None:
    await page.goto(settings.expoyer_base_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
    await page.get_by_text("LOGIN", exact=False).first.click()
    await page.wait_for_timeout(1500)
    await page.locator("#login-user").fill(settings.expoyer_user)
    await page.locator("#login-password").fill(settings.expoyer_password)
    await page.get_by_role("button", name=re.compile(r"ingresar", re.I)).click()
    await page.wait_for_timeout(4000)
    await shot(page, "expoyer-after")
    print("login-user vis", await page.locator("#login-user").locator("visible=true").count())
    print("search", await page.locator("input[type=search], #nav_id").count())


async def main() -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(locale="es-AR", viewport={"width": 1400, "height": 900})
        try:
            await infobal(page)
            await expoyer(page)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
