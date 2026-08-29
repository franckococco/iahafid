"""Explora búsqueda en Infobal, Expoyer y Service Box. No imprime claves."""

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


async def dump(page, name: str) -> None:
    path = _ROOT / "data" / f"probe-{name}.png"
    await page.screenshot(path=str(path), full_page=False)
    inputs = await page.locator("input, textarea").evaluate_all(
        """els => els.slice(0, 25).map(e => ({
            tag: e.tagName, type: e.type, name: e.name, id: e.id,
            ph: e.placeholder, aria: e.getAttribute('aria-label'), vis: !!(e.offsetParent)
        }))"""
    )
    links = await page.locator("a, button").evaluate_all(
        """els => els.slice(0, 40).map(e => (e.innerText || e.value || '').trim()).filter(Boolean)"""
    )
    print(f"--- {name} url={page.url[:120]}")
    print("inputs", inputs)
    print("buttons", links[:25])
    print("body", (await page.inner_text("body"))[:400].replace("\n", " | "))


async def infobal(page) -> None:
    print("=== Infobal search ===")
    await page.goto(settings.infobal_base_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
    user = page.locator("input[type='text'], input[name*='user' i]").locator("visible=true")
    pwd = page.locator("input[type='password']").locator("visible=true")
    if await user.count() and await pwd.count():
        await user.first.fill(settings.infobal_user)
        await pwd.first.fill(settings.infobal_password)
        btn = page.get_by_role("button", name=re.compile(r"acceder|ingresar|login", re.I))
        if await btn.count() == 0:
            btn = page.locator("button, input[type=submit]").locator("visible=true")
        await btn.first.click()
        await page.wait_for_timeout(4000)
    await dump(page, "infobal-home")
    box = page.get_by_placeholder(re.compile(r"buscar|search|producto", re.I))
    if await box.count() == 0:
        box = page.locator("input[type='search'], input[aria-label*='buscar' i]")
    if await box.count() == 0:
        box = page.locator("header input, .t-NavigationBar input, input.a-TextField")
    print("search boxes", await box.count())
    if await box.count():
        await box.first.click()
        await box.first.fill("radiador partner")
        await box.first.press("Enter")
        await page.wait_for_timeout(4500)
        await dump(page, "infobal-radiador")


async def expoyer(page) -> None:
    print("=== Expoyer login ===")
    await page.goto(settings.expoyer_base_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    login = page.get_by_role("link", name=re.compile(r"^login$", re.I))
    if await login.count() == 0:
        login = page.get_by_text("LOGIN", exact=False)
    if await login.count():
        await login.first.click()
        await page.wait_for_timeout(2500)
    await dump(page, "expoyer-login")
    user = page.locator("input[type='text'], input[type='email'], input[name*='user' i]").locator("visible=true")
    pwd = page.locator("input[type='password']").locator("visible=true")
    print("expoyer fields", await user.count(), await pwd.count())
    if await user.count() and await pwd.count():
        await user.first.fill(settings.expoyer_user)
        await pwd.first.fill(settings.expoyer_password)
        btn = page.get_by_role("button", name=re.compile(r"ingresar|login|acceder|entrar", re.I))
        if await btn.count() == 0:
            btn = page.locator("button[type=submit], input[type=submit]").locator("visible=true")
        if await btn.count():
            await btn.first.click()
            await page.wait_for_timeout(4000)
        await dump(page, "expoyer-in")
        box = page.get_by_placeholder(re.compile(r"buscar|search|producto|codigo", re.I))
        if await box.count() == 0:
            box = page.locator("input[type='search'], header input")
        print("expoyer search", await box.count())
        if await box.count():
            await box.first.fill("radiador partner")
            await box.first.press("Enter")
            await page.wait_for_timeout(4000)
            await dump(page, "expoyer-radiador")


async def servicebox(page) -> None:
    print("=== Service Box ===")
    await page.goto(settings.servicebox_base_url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3000)
    await dump(page, "servicebox-lang")
    for label in (
        "Español (Argentina)",
        "Español",
        "Argentina",
        "Français",
        "English",
    ):
        loc = page.get_by_text(label, exact=False)
        if await loc.count():
            print("click language", label)
            try:
                await loc.first.click(timeout=8000)
                await page.wait_for_timeout(2500)
                break
            except Exception as exc:
                print("lang click fail", exc)
    await dump(page, "servicebox-login")
    user = page.locator("#username, input[name='username'], input[id*='user' i]")
    pwd = page.locator("#password, input[name='password'], input[type='password']")
    print("sb fields", await user.count(), await pwd.count())
    if await user.count() and await pwd.count():
        await user.first.fill(settings.servicebox_user, timeout=8000)
        await pwd.first.fill(settings.servicebox_password, timeout=8000)
        btn = page.locator("#btsubmit, #conx-btn, button[type=submit], input[type=submit]")
        if await btn.count() == 0:
            btn = page.get_by_role("button", name=re.compile(r"conex|connect|entrar|ok", re.I))
        if await btn.count():
            await btn.first.click()
            await page.wait_for_timeout(6000)
    await dump(page, "servicebox-in")
    vin = page.get_by_placeholder(re.compile(r"vin|vis|chasis|chassis", re.I))
    if await vin.count() == 0:
        vin = page.locator("input[name*='vin' i], input[id*='vin' i], input[name*='vis' i]")
    print("vin boxes", await vin.count())
    if await vin.count():
        await vin.first.fill("8G535332")
        ok = page.get_by_role("button", name=re.compile(r"^ok$|buscar|search", re.I))
        if await ok.count():
            await ok.first.click()
            await page.wait_for_timeout(5000)
        await dump(page, "servicebox-vin")


async def main() -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(locale="es-AR", viewport={"width": 1400, "height": 900})
        page = await context.new_page()
        page.set_default_timeout(25000)
        try:
            await infobal(page)
            await expoyer(page)
            await servicebox(page)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
