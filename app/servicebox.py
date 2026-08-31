"""Service Box (Peugeot / Citroën OEM). Login Stellantis SSO; si falla, vacío."""

from __future__ import annotations

import asyncio
import logging
import re

from app.browser import chromium_launch_kwargs
from app.config import _ROOT, settings
from app.sales import catalog_close, catalog_search_query, fold

logger = logging.getLogger(__name__)

_STATE = _ROOT / "data" / "servicebox-state.json"
_DEBUG = _ROOT / "data" / "servicebox-debug.png"
_LOCK = asyncio.Lock()
_PART_CODE = re.compile(r"\b\d{4}[.\s][A-Z0-9]{1,4}\b|\b\d{8,10}\b", re.I)
_BAD_LOGIN = (
    "no validos",
    "no válidos",
    "invalid username",
    "invalid password",
    "usuario o contrasena",
)


def enabled() -> bool:
    return bool(
        settings.servicebox_enabled
        and settings.servicebox_user
        and settings.servicebox_password
    )


def format_results(chasis: str, vehicle: str, rows: list[dict]) -> str:
    if not rows:
        return ""
    vehicle_bit = f" ({vehicle})" if vehicle else ""
    lines = [f"En Service Box para el chasis {chasis}{vehicle_bit} aparece:"]
    for item in rows[:5]:
        piece = " — ".join(
            part for part in (item.get("code") or "", item.get("name") or "") if part
        )
        if piece:
            lines.append(f"- {piece}")
    lines.append(catalog_close(len(rows)))
    return "\n".join(lines)


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
    browser = await playwright.chromium.launch(**chromium_launch_kwargs())
    context = None
    try:
        kwargs: dict = {"locale": "es-AR", "viewport": {"width": 1400, "height": 900}}
        if _STATE.exists():
            kwargs["storage_state"] = str(_STATE)
        context = await browser.new_context(**kwargs)
        page = await context.new_page()
        page.set_default_timeout(25000)
        await page.goto(settings.servicebox_base_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)
        body = fold(await page.inner_text("body"))
        if "problema tecnico" in body or "technical problem" in body:
            logger.warning("Service Box: sitio con problema técnico")
            return ""
        await _pick_spanish(page)
        if not await _ensure_login(page):
            await _shot(page)
            return ""
        vin = await _vin_box(page)
        if vin is None:
            logger.warning("Service Box: no vi el campo VIN")
            await _shot(page)
            return ""
        await vin.fill(chasis)
        ok = page.get_by_role("button", name=re.compile(r"^ok$|buscar|search|valider", re.I))
        if await ok.count():
            await ok.first.click()
        else:
            await vin.press("Enter")
        await page.wait_for_timeout(4000)
        term = catalog_search_query(query) or query
        box = await _part_box(page)
        if box is not None and term:
            await box.fill(term)
            await box.press("Enter")
            await page.wait_for_timeout(4000)
        try:
            await context.storage_state(path=str(_STATE))
        except Exception:
            pass
        text = " ".join((await page.inner_text("body")).split())
        if not text or "problema técnico" in text.lower():
            logger.warning("Service Box: página vacía o caída después del chasis")
            await _shot(page)
            return ""
        vehicle = _vehicle_from_body(text)
        rows = _parse_parts(text, term)
        if rows:
            logger.info("Service Box: %s filas para %s / %s", len(rows), chasis, term)
            return format_results(chasis, vehicle, rows)
        logger.info("Service Box: chasis %s sin pieza %s (auto=%s)", chasis, term, vehicle)
        await _shot(page)
        return ""
    finally:
        if context:
            await context.close()
        await browser.close()
        await playwright.stop()


async def _pick_spanish(page) -> None:
    current = page.get_by_text(re.compile(r"Français \(France\)|Español", re.I))
    if await current.count():
        try:
            await current.first.click(timeout=4000)
            await page.wait_for_timeout(600)
        except Exception:
            pass
    for label in ("Español (Argentina)", "Español", "English"):
        loc = page.get_by_text(label, exact=False)
        if await loc.count():
            try:
                await loc.first.click(timeout=5000)
                await page.wait_for_timeout(1500)
                return
            except Exception:
                continue


async def _accept_cookies(page) -> None:
    for name in (r"^aceptar$", r"^accept$", r"^ok$"):
        loc = page.get_by_role("button", name=re.compile(name, re.I))
        if await loc.count() == 0:
            loc = page.get_by_text(re.compile(name, re.I))
        if await loc.count():
            try:
                await loc.first.click(timeout=4000, force=True)
                await page.wait_for_timeout(800)
                return
            except Exception:
                continue


async def _ensure_login(page) -> bool:
    if await _vin_box(page) is not None:
        logger.info("Service Box: sesión vigente")
        return True
    btn = page.locator("#conx-btn")
    if await btn.count() == 0:
        btn = page.get_by_role(
            "button", name=re.compile(r"connexion|conexion|conectar", re.I)
        )
    if await btn.count():
        try:
            async with page.expect_navigation(timeout=20000):
                await btn.first.click()
        except Exception:
            await btn.first.click()
        await page.wait_for_timeout(2500)
    await _accept_cookies(page)
    await page.wait_for_timeout(1200)
    if await _vin_box(page) is not None:
        return True
    user = page.get_by_label(re.compile(r"username|usuario", re.I))
    pwd = page.get_by_label(re.compile(r"contraseña|password", re.I))
    if await user.count() == 0 or await pwd.count() == 0:
        user = page.locator("input[name='username']").locator("visible=true")
        pwd = page.locator("input[name='password']").locator("visible=true")
    if await user.count() == 0 or await pwd.count() == 0:
        logger.warning("Service Box: no vi el login Stellantis")
        return False
    await user.first.fill(settings.servicebox_user, force=True)
    await pwd.first.fill(settings.servicebox_password, force=True)
    enviar = page.get_by_role("button", name=re.compile(r"^enviar$|^login$|^connexion$", re.I))
    if await enviar.count() == 0:
        enviar = page.locator("input[type=submit], button[type=submit]").locator("visible=true")
    if await enviar.count():
        await enviar.first.click()
    else:
        await pwd.first.press("Enter")
    await page.wait_for_timeout(6000)
    blob = fold(await page.inner_text("body"))
    if any(marker in blob for marker in _BAD_LOGIN):
        logger.warning("Service Box: usuario o clave rechazados en el login Stellantis")
        return False
    if await _vin_box(page) is None and "login-saml" in page.url:
        logger.warning("Service Box: seguí en el login, no entré al catálogo")
        return False
    logger.info("Service Box: sesión iniciada")
    return True


async def _vin_box(page):
    for frame in page.frames:
        loc = frame.get_by_placeholder(
            re.compile(r"vin|vis|chasis|chassis", re.I)
        ).locator("visible=true")
        if await loc.count():
            return loc.first
        loc = frame.locator(
            "input[name*='vin' i], input[id*='vin' i], input[name*='vis' i], input[id*='vis' i]"
        ).locator("visible=true")
        if await loc.count():
            return loc.first
    return None


async def _part_box(page):
    for frame in page.frames:
        loc = frame.get_by_placeholder(
            re.compile(r"pieza|part|recherch|buscar|search", re.I)
        ).locator("visible=true")
        if await loc.count():
            return loc.first
    return None


async def _shot(page) -> None:
    try:
        _DEBUG.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(_DEBUG), full_page=False)
    except Exception:
        pass


def _vehicle_from_body(text: str) -> str:
    blob = " ".join(text.split())
    for needle in ("Peugeot", "Citroën", "Citroen", "DS ", "Opel"):
        idx = blob.find(needle)
        if idx >= 0:
            return blob[idx : idx + 80].strip(" ,-|")
    return ""


def _parse_parts(text: str, query: str) -> list[dict]:
    wanted = fold(query)
    rows: list[dict] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if len(line) < 8:
            continue
        code_m = _PART_CODE.search(line)
        if not code_m:
            continue
        code = code_m.group(0).upper()
        if code in seen:
            continue
        name = fold(line)
        if wanted and not any(word in name for word in wanted.split() if len(word) > 3):
            continue
        seen.add(code)
        rows.append({"code": code, "name": line[:90]})
        if len(rows) >= 8:
            break
    return rows
