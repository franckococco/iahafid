"""Entra a Service Box, pega 8G535332 y busca disco de embrague. No imprime claves."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_ROOT / ".playwright-browsers"))

from app.browser import chromium_launch_kwargs  # noqa: E402
from app.config import _ROOT, settings  # noqa: E402

VIN = "8G535332"
OUT = _ROOT / "data"


async def dump(page, name: str) -> None:
    path = OUT / f"probe-{name}.png"
    await page.screenshot(path=str(path), full_page=False)
    frames = page.frames
    print(f"--- {name} url={page.url[:140]} frames={len(frames)}")
    for i, frame in enumerate(frames[:8]):
        try:
            url = frame.url[:120]
            inputs = await frame.locator("input, textarea, select").evaluate_all(
                """els => els.slice(0, 30).map(e => ({
                    tag: e.tagName, type: e.type, name: e.name, id: e.id,
                    ph: e.placeholder, aria: e.getAttribute('aria-label'),
                    vis: !!(e.offsetParent)
                }))"""
            )
            text = " ".join((await frame.inner_text("body")).split())[:500]
            print(f"  frame{i} {url}")
            print("  inputs", json.dumps(inputs, ensure_ascii=False)[:900])
            print("  body", text.replace("\n", " | ")[:400])
        except Exception as exc:
            print(f"  frame{i} err {type(exc).__name__}: {exc}")


async def click_lang(page) -> None:
    current = page.get_by_text(re.compile(r"Français \(France\)|Español", re.I))
    if await current.count():
        try:
            await current.first.click(timeout=4000)
            await page.wait_for_timeout(800)
        except Exception:
            pass
    for label in ("Español (Argentina)", "Español", "English"):
        loc = page.get_by_text(label, exact=False)
        if await loc.count():
            try:
                await loc.first.click(timeout=5000)
                await page.wait_for_timeout(2000)
                print("lang", label)
                return
            except Exception:
                continue
    print("lang unchanged")


async def visible_login(page):
    user = page.locator(
        "#username, input[name='username'], input[name='j_username'], "
        "input[type='text'], input[type='email']"
    ).locator("visible=true")
    pwd = page.locator(
        "#password, input[name='password'], input[name='j_password'], input[type='password']"
    ).locator("visible=true")
    return user, pwd


async def login(page) -> None:
    user, pwd = await visible_login(page)
    print("login fields before connexion", await user.count(), await pwd.count())
    if await user.count() == 0 or await pwd.count() == 0:
        btn = page.locator("#conx-btn")
        if await btn.count() == 0:
            btn = page.get_by_role("button", name=re.compile(r"connexion|conexion|entrar|login", re.I))
        if await btn.count() == 0:
            btn = page.get_by_text(re.compile(r"^connexion$|^conectar$|^entrar$", re.I))
        print("connexion buttons", await btn.count())
        if await btn.count():
            try:
                async with page.expect_navigation(timeout=20000):
                    await btn.first.click()
            except Exception:
                await btn.first.click()
            await page.wait_for_timeout(2500)
            aceptar = page.get_by_role("button", name=re.compile(r"^aceptar$|^accept$|^ok$", re.I))
            if await aceptar.count() == 0:
                aceptar = page.get_by_text(re.compile(r"^aceptar$", re.I))
            if await aceptar.count():
                try:
                    await aceptar.first.click(timeout=4000)
                    print("accepted cookies")
                except Exception:
                    print("cookie click failed")
            await page.wait_for_timeout(2000)
            try:
                await page.wait_for_selector(
                    "input[type='password'], input[name='username'], input[name='j_username']",
                    timeout=20000,
                    state="visible",
                )
            except Exception:
                print("password field never appeared")
            await dump(page, "sb-sso")
            all_inputs = await page.locator("input").evaluate_all(
                """els => els.map(e => ({
                    type: e.type, name: e.name, id: e.id, ph: e.placeholder,
                    vis: !!(e.offsetParent)
                }))"""
            )
            print("all inputs", json.dumps(all_inputs, ensure_ascii=False)[:1200])
            user, pwd = await visible_login(page)
            print("login fields after connexion", await user.count(), await pwd.count(), "url", page.url[:120])
    if await user.count() and await pwd.count():
        await user.first.fill(settings.servicebox_user)
        await pwd.first.fill(settings.servicebox_password)
        submit = page.locator(
            "#btsubmit, button[type=submit], input[type=submit]"
        ).locator("visible=true")
        if await submit.count() == 0:
            submit = page.get_by_role(
                "button",
                name=re.compile(r"conex|connect|entrar|ok|suivant|continuar|login", re.I),
            )
        if await submit.count():
            await submit.first.click()
            await page.wait_for_timeout(6000)
            print("clicked login submit")
        else:
            await pwd.first.press("Enter")
            await page.wait_for_timeout(6000)
            print("pressed enter on password")
    else:
        print("still no login fields")


async def find_vin(page):
    for frame in page.frames:
        vin = frame.get_by_placeholder(re.compile(r"vin|vis|chasis|chassis", re.I)).locator("visible=true")
        if await vin.count():
            return frame, vin
        vin = frame.locator(
            "input[name*='vin' i], input[id*='vin' i], input[name*='vis' i], input[id*='vis' i]"
        ).locator("visible=true")
        if await vin.count():
            return frame, vin
    return None, None


async def main() -> None:
    from playwright.async_api import async_playwright

    print("user set", bool(settings.servicebox_user), "url", settings.servicebox_base_url)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(**chromium_launch_kwargs())
        context = await browser.new_context(locale="es-AR", viewport={"width": 1400, "height": 900})
        page = await context.new_page()
        page.set_default_timeout(25000)
        try:
            await page.goto(settings.servicebox_base_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)
            await dump(page, "sb-start")
            await click_lang(page)
            await dump(page, "sb-lang")
            await login(page)
            await dump(page, "sb-in")
            frame, vin = await find_vin(page)
            print("vin boxes", await vin.count() if vin else 0)
            if vin and await vin.count():
                await vin.first.fill(VIN)
                ok = frame.get_by_role("button", name=re.compile(r"^ok$|buscar|search|valider", re.I))
                if await ok.count() == 0:
                    ok = frame.locator("button").locator("visible=true")
                if await ok.count():
                    await ok.first.click()
                    print("clicked vin ok")
                else:
                    await vin.first.press("Enter")
                    print("pressed enter on vin")
                await page.wait_for_timeout(5000)
            await dump(page, "sb-vin")
            box = None
            for fr in page.frames:
                loc = fr.get_by_placeholder(
                    re.compile(r"pieza|part|recherch|search|buscar", re.I)
                ).locator("visible=true")
                if await loc.count():
                    box = loc
                    break
            print("part search box", await box.count() if box else 0)
            if box and await box.count():
                await box.first.fill("disco embrague")
                await box.first.press("Enter")
                await page.wait_for_timeout(4500)
                await dump(page, "sb-embrague")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
