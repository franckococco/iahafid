"""Consulta PartsLink24: el software entra, pega el chasis y lee la tabla. Gemini no busca."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re

from pathlib import Path

from app.config import _ROOT, settings
from app.sales import (
    axle_wanted,
    fold,
    needs_axle_clarify,
    needs_side_clarify,
    pump_kind_wanted,
    search_queries,
    side_wanted,
)

# Cursor a veces apunta Playwright a un cache temporal sin Chrome.
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_ROOT / ".playwright-browsers")

logger = logging.getLogger(__name__)

_STATE = _ROOT / "data" / "partslink-state.json"
_DEBUG = _ROOT / "data" / "partslink-debug.png"
_CHASSIS_FILE = _ROOT / "data" / "peugeot-chasis.json"
_LOCK = asyncio.Lock()

_PART_NO = re.compile(
    r"\b[A-Z0-9]{2,3}\s?[A-Z0-9]{3}\s?[A-Z0-9]{3}(?:\s?[A-Z0-9])?\b",
    re.IGNORECASE,
)


def _short_spec(chasis: str) -> dict:
    """Ficha de un chasis de 8 dígitos (lista del local / AMLAT)."""
    if not _CHASSIS_FILE.exists():
        return {}
    try:
        data = json.loads(_CHASSIS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    item = data.get(chasis.strip().upper())
    return item if isinstance(item, dict) else {}


class PartsLinkError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(
        settings.partslink24_enabled
        and settings.partslink24_company_id
        and settings.partslink24_user
        and settings.partslink24_password
    )


def format_results(chasis: str, vehicle: str, rows: list[dict], ask: str = "") -> str:
    if ask:
        return (
            f"Con el chasis {chasis} hay más de una variante. "
            f"¿La pieza es {ask}? Así te paso el código justo, no todos."
        )
    if not rows:
        return (
            f"Con el chasis {chasis} no pude ubicar esa pieza en el catálogo. "
            "Te dejo con un vendedor para que lo mire."
        )
    vehicle_bit = ""
    if vehicle:
        clean = re.sub(re.escape(chasis), "", vehicle, flags=re.IGNORECASE)
        clean = re.sub(r"partslink24", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s{2,}", " ", clean).strip(" ,-")
        if clean:
            vehicle_bit = f" ({clean})"
    lines = [f"Para el chasis {chasis}{vehicle_bit} aparece:"]
    for item in rows[:5]:
        code = item.get("code") or ""
        name = item.get("name") or ""
        extra = item.get("note") or ""
        piece = " — ".join(part for part in (code, name) if part)
        if extra and extra not in piece:
            piece = f"{piece} ({extra})"
        lines.append(f"- {piece}")
    if len(rows) > 5:
        lines.append("Hay más variantes; si querés te lo confirma un vendedor.")
    else:
        lines.append("El precio te lo confirmamos en el local. ¿Lo encargamos?")
    lines.append("Si querés el despiece, pedime la foto. Otro auto o pieza: *nuevo pedido*.")
    return "\n".join(lines)


async def lookup(
    chasis: str,
    query: str,
    screenshot_to: str | None = None,
    brand: str = "",
    model: str = "",
) -> dict:
    """Devuelve vehicle + filas de la tabla. No inventa precios."""
    if not enabled():
        raise PartsLinkError("Faltan las claves de PartsLink24 en el .env")
    if not chasis or not query:
        raise PartsLinkError("Hace falta chasis y pieza")
    async with _LOCK:
        return await _lookup_locked(
            chasis.strip().upper(),
            query.strip(),
            screenshot_to,
            brand.strip().lower(),
            model.strip(),
        )


async def _lookup_locked(
    chasis: str,
    query: str,
    screenshot_to: str | None = None,
    brand: str = "",
    model: str = "",
) -> dict:
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    context = None
    page = None
    try:
        context_kwargs: dict = {
            "locale": "es-AR",
            "viewport": {"width": 1400, "height": 900},
        }
        if _STATE.exists():
            context_kwargs["storage_state"] = str(_STATE)
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        page.set_default_timeout(25000)
        await _ensure_logged_in(page)
        vehicle = await _search_chassis(page, chasis, brand=brand, model=model)
        rows = await _search_parts(page, query)
        rows, ask = _narrow_rows(rows, query)
        if screenshot_to and rows and not ask:
            path = Path(screenshot_to)
            path.parent.mkdir(parents=True, exist_ok=True)
            opened = await _open_diagram(page, rows)
            captured = False
            if opened:
                captured = await _capture_diagram(page, path)
            if captured:
                logger.info("PartsLink24 despiece en %s", path)
            else:
                logger.warning("PartsLink24: no hay lámina para fotografiar")
                if path.exists():
                    path.unlink()
        _STATE.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(_STATE))
        return {"vehicle": vehicle, "rows": rows, "ask": ask}
    except Exception:
        if page is not None:
            try:
                await page.screenshot(path=str(_DEBUG), full_page=True)
                logger.warning("PartsLink24 falló; captura en %s", _DEBUG)
            except Exception:
                logger.exception("No pude guardar la captura de PartsLink24")
        raise
    finally:
        if context is not None:
            await context.close()
        await browser.close()
        await playwright.stop()


async def _settle_home(page) -> None:
    for _ in range(30):
        if await _chassis_box(page).count():
            return
        if await _login_visible(page):
            return
        await page.wait_for_timeout(400)


async def _ensure_logged_in(page) -> None:
    await page.goto(settings.partslink24_base_url, wait_until="domcontentloaded")
    await _settle_home(page)
    if await _chassis_box(page).count():
        logger.info("PartsLink24: sesión vigente")
        return
    if not await _login_visible(page):
        await page.goto(
            settings.partslink24_base_url.rstrip("/") + "/",
            wait_until="domcontentloaded",
        )
        await _settle_home(page)
    if not await _login_visible(page) and await _chassis_box(page).count():
        return
    logger.info("PartsLink24: inicio de sesión")
    company = page.locator('[data-test-id="pl24-login-ui-loginForm-input-companyId"]').locator("visible=true")
    user = page.locator('[data-test-id="pl24-login-ui-loginForm-input-username"]').locator("visible=true")
    password = page.locator('[data-test-id="pl24-login-ui-loginForm-input-password"]').locator("visible=true")
    if await company.count() == 0:
        company = page.locator('input[name="companyId"]').locator("visible=true")
        user = page.locator('input[name="username"]').locator("visible=true")
        password = page.locator('input[type="password"]').locator("visible=true")
    await company.first.fill(settings.partslink24_company_id)
    await user.first.fill(settings.partslink24_user)
    await password.first.fill(settings.partslink24_password)
    button = page.get_by_role("button", name=re.compile(r"iniciar sesi[oó]n|log in", re.I)).locator("visible=true")
    await button.first.click()
    confirm = page.get_by_role("button", name=re.compile(r"^confirmar$", re.I))
    try:
        await confirm.first.wait_for(state="visible", timeout=8000)
        await confirm.first.click()
        logger.info("PartsLink24: confirmé reemplazar la sesión abierta")
    except Exception:
        logger.info("PartsLink24: no pidió confirmar sesión")
    try:
        await _chassis_box(page).first.wait_for(state="visible", timeout=30000)
    except Exception as exc:
        raise PartsLinkError("No pude entrar a PartsLink24. Revisá usuario y clave.") from exc


async def _login_visible(page) -> bool:
    password = page.locator('input[type="password"]').locator("visible=true")
    return await password.count() > 0


def _chassis_box(page):
    return page.get_by_placeholder(
        re.compile(
            r"n[uú]mero de chasis|chassis|bastidor|\bvin\b|identificaci[oó]n|acceso directo|direct access",
            re.I,
        )
    )


def _parts_box(page):
    return page.get_by_placeholder(re.compile(r"buscar piezas|search parts", re.I)).locator(
        "visible=true"
    )


_BRAND_LABEL = {
    "peugeot": r"peugeot",
    "citroen": r"citro[eë]n",
    "volkswagen": r"volkswagen|\bvw\b",
}


async def _dismiss_dialogs(page) -> None:
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    for pattern in (
        r"^cerrar$",
        r"^close$",
        r"^ok$",
        r"^aceptar$",
        r"^entendido$",
    ):
        btn = page.get_by_role("button", name=re.compile(pattern, re.I))
        try:
            if await btn.count():
                await btn.first.click(timeout=1200)
        except Exception:
            continue
    for loc in (
        page.locator('[aria-label="Close"]'),
        page.locator('[aria-label="Cerrar"]'),
        page.locator('[aria-label="close" i]'),
    ):
        try:
            if await loc.count():
                await loc.first.click(timeout=800)
        except Exception:
            continue


async def _already_in_brand(page, brand: str) -> bool:
    key = fold(brand)
    if key and key in page.url.lower() and "partslink24.com/" in page.url.lower():
        path = page.url.lower().split("partslink24.com", 1)[-1]
        if key in path:
            return True
    try:
        body = fold(await page.inner_text("body"))
    except Exception:
        return False
    return "resumen de modelos" in body


async def _wait_in_brand(page, brand: str, timeout_ms: int = 25000) -> bool:
    elapsed = 0
    while elapsed < timeout_ms:
        if await _already_in_brand(page, brand):
            await page.wait_for_timeout(600)
            return True
        await page.wait_for_timeout(400)
        elapsed += 400
    return False


async def _wait_catalog_ready(page, timeout_ms: int = 35000) -> bool:
    elapsed = 0
    while elapsed < timeout_ms:
        if await _chassis_box(page).locator("visible=true").count():
            await page.wait_for_timeout(600)
            return True
        await page.wait_for_timeout(400)
        elapsed += 400
    return False


async def _open_brand_catalog(page, brand: str) -> bool:
    """En la grilla de marcas, entra al catálogo (Peugeot, etc.)."""
    key = fold(brand)
    title = {"peugeot": "Peugeot", "citroen": "Citroën", "volkswagen": "Volkswagen"}.get(
        key, brand.title()
    )
    logo = page.locator(f'img[alt="{title}"]')
    if await logo.count() == 0:
        logo = page.locator(f'img[src*="/carbrands/{key}/"]')
    try:
        await logo.first.wait_for(state="visible", timeout=20000)
    except Exception:
        logger.warning("PartsLink24: no encontré el logo de %s", brand)
        return False
    try:
        await logo.first.scroll_into_view_if_needed()
        parent = logo.first.locator("xpath=ancestor::*[self::a or self::button][1]")
        if await parent.count():
            await parent.click(timeout=4000, force=True)
        else:
            await logo.first.click(timeout=4000, force=True)
    except Exception:
        logger.warning("PartsLink24: no pude cliclear %s", brand)
        return False
    logger.info("PartsLink24: clic catálogo %s", brand)
    try:
        await page.wait_for_url(re.compile(key, re.I), timeout=15000)
    except Exception:
        await page.wait_for_timeout(1200)
    ready = await _wait_in_brand(page, brand, timeout_ms=25000)
    logger.info("PartsLink24 URL %s ready=%s", page.url, ready)
    return ready


async def _submit_chassis(page, chasis: str) -> bool:
    if not await _wait_catalog_ready(page, timeout_ms=8000):
        return False
    box = _chassis_box(page).locator("visible=true")
    if await box.count() == 0:
        labeled = page.get_by_label(re.compile(r"acceso directo", re.I))
        if await labeled.count() == 0:
            return False
        box = labeled
    await box.first.fill("")
    await box.first.fill(chasis)
    await box.first.press("Enter")
    try:
        await _parts_box(page).first.wait_for(state="visible", timeout=8000)
        return True
    except Exception:
        await page.wait_for_timeout(2500)
    try:
        body = fold(await page.inner_text("body"))
    except Exception:
        body = ""
    if any(
        marker in body
        for marker in (
            "no pudo ser asignado",
            "catalogo correcto",
            "no se han encontrado entradas",
            "intentalo de nuevo",
        )
    ):
        return False
    if await page.get_by_text(re.compile(r"grupo principal|despiece|l[aá]mina", re.I)).count():
        return True
    return await _parts_box(page).count() > 0


async def _click_visible_text(page, *candidates: str) -> bool:
    await _dismiss_dialogs(page)
    for raw in candidates:
        text = (raw or "").strip()
        if not text:
            continue
        loc = page.get_by_text(text, exact=True)
        if await loc.count() == 0:
            loc = page.get_by_text(re.compile(re.escape(text), re.I))
        n = await loc.count()
        if not n:
            continue
        try:
            await loc.nth(n - 1).click(force=True, timeout=8000)
            await page.wait_for_timeout(1100)
            logger.info("PartsLink24 clic %r", text)
            return True
        except Exception:
            continue
    return False


def _body_labels(carroceria: str) -> list[str]:
    blob = (carroceria or "").upper()
    labels = [carroceria] if carroceria else []
    mapping = {
        "BERLINA 5 PUERTAS": ("BERLINA DE 5 PUERTAS", "BERLINA 5 PUERTAS"),
        "BERLINA 4 PUERTAS": ("BERLINA DE 4 PUERTAS", "BERLINA 4 PUERTAS"),
        "BERLINA 3 PUERTAS": ("BERLINA DE 3 PUERTAS", "BERLINA 3PTAS", "BERLINA 3 PUERTAS"),
    }
    for key, alts in mapping.items():
        if key in blob:
            labels.extend(alts)
    return list(dict.fromkeys(labels))


async def _drill_known_vehicle(page, spec: dict) -> bool:
    """Baja por modelo → AMLAT → carrocería → motor. No usa Acceso directo."""
    model = str(spec.get("modelo") or "")
    if not model:
        return False
    logger.info(
        "PartsLink24 identifica %s %s amlat=%s %s %s",
        model,
        spec.get("carroceria"),
        spec.get("amlat"),
        spec.get("motor_code") or spec.get("motor"),
        spec.get("caja"),
    )
    await _dismiss_dialogs(page)
    try:
        await page.get_by_text("Resumen de modelos", exact=False).first.wait_for(timeout=15000)
        await page.get_by_text(model, exact=True).first.wait_for(state="visible", timeout=15000)
    except Exception:
        logger.warning("PartsLink24: no vi el modelo %s", model)
        return False
    await page.get_by_text(model, exact=True).first.click(force=True)
    await page.wait_for_timeout(1200)
    if spec.get("amlat"):
        if not await _click_visible_text(
            page,
            f"{model} / HOGGAR (AMLAT)",
            f"{model} / HOGGAR",
            "HOGGAR (AMLAT)",
        ):
            logger.warning("PartsLink24: no vi variante AMLAT del %s", model)
            return False
    else:
        variants = page.get_by_text(model, exact=True)
        if await variants.count() >= 2:
            await variants.nth(1).click(force=True)
            await page.wait_for_timeout(1100)
    if not await _click_visible_text(page, *_body_labels(str(spec.get("carroceria") or ""))):
        logger.warning("PartsLink24: no vi carrocería %s", spec.get("carroceria"))
        return False
    motor_ok = False
    code = str(spec.get("motor_code") or "").strip()
    if code and await _click_visible_text(page, code):
        motor_ok = True
    if not motor_ok:
        motor = str(spec.get("motor") or "").strip()
        if motor:
            motor_ok = await _click_visible_text(page, motor, motor.replace("  ", " "))
    if not motor_ok:
        logger.warning("PartsLink24: no vi el motor %s", code or spec.get("motor"))
        return False
    caja = str(spec.get("caja") or "").strip()
    if caja:
        await _click_visible_text(page, caja, caja.replace(" ", ""), "CVM 5", "CVM5", "CVM 6", "CVM6")
    await page.wait_for_timeout(1500)
    try:
        await _parts_box(page).first.wait_for(state="visible", timeout=12000)
    except Exception:
        await page.wait_for_timeout(800)
    return True


async def _search_chassis(page, chasis: str, brand: str = "", model: str = "") -> str:
    short = 8 <= len(chasis) < 17
    brands: list[str] = []
    if brand:
        brands.append(brand)
    elif short:
        brands.append("peugeot")
    if short:
        for name in brands:
            await _dismiss_dialogs(page)
            if not await _already_in_brand(page, name):
                await _open_brand_catalog(page, name)
            await _dismiss_dialogs(page)
            if not await _already_in_brand(page, name):
                logger.warning("PartsLink24: no entré al catálogo %s", name)
                continue
            spec = _short_spec(chasis)
            if spec:
                if await _drill_known_vehicle(page, spec):
                    label = " ".join(
                        part
                        for part in (
                            spec.get("modelo"),
                            spec.get("anio"),
                            "AMLAT" if spec.get("amlat") else "",
                            spec.get("carroceria"),
                            spec.get("motor"),
                        )
                        if part
                    )
                    return label.strip() or chasis
                logger.warning("PartsLink24: no pude armar el auto de la ficha %s", chasis)
            if await _submit_chassis(page, chasis):
                return await _vehicle_name(page)
            logger.warning("PartsLink24: %s no abrió con catálogo %s", chasis, name)
        raise PartsLinkError(
            f"El chasis {chasis} no se asignó en el catálogo {brands[0] if brands else 'de la marca'}"
        )
    if await _submit_chassis(page, chasis):
        return await _vehicle_name(page)
    if brand:
        await _dismiss_dialogs(page)
        await _open_brand_catalog(page, brand)
        await _dismiss_dialogs(page)
        if await _submit_chassis(page, chasis):
            return await _vehicle_name(page)
    raise PartsLinkError("El chasis no abrió el catálogo del auto")


async def _vehicle_name(page) -> str:
    body = fold(await page.inner_text("body"))
    for marker in ("modelo", "identificacion del vehiculo"):
        if marker in body:
            break
    crumbs = page.locator("text=/Amarok|Golf|Gol|Peugeot|Citro|308|C3|Amarok/i")
    if await crumbs.count():
        return (await crumbs.first.inner_text()).strip()[:80]
    title = await page.title()
    return title.strip()[:80]


async def _run_part_search(page, term: str) -> list[dict]:
    box = _parts_box(page)
    if await box.count() == 0:
        raise PartsLinkError("No encontré 'Buscar piezas' después del chasis")
    await box.first.click()
    await box.first.fill("")
    await box.first.fill(term)
    await page.wait_for_timeout(800)
    await box.first.press("Enter")
    await page.wait_for_timeout(2500)
    rows = await _read_search_list(page)
    if not rows:
        rows = await _read_rows(page)
    if rows:
        return rows
    hint = term.split()[0] if term.split() else term
    suggestion = page.get_by_text(re.compile(re.escape(hint), re.I)).locator("visible=true")
    if await suggestion.count() > 1:
        await suggestion.nth(1).click(force=True)
        await page.wait_for_timeout(2500)
        return await _read_search_list(page) or await _read_rows(page)
    return []


async def _search_parts(page, query: str) -> list[dict]:
    last: list[dict] = []
    for term in search_queries(query)[:2]:
        logger.info("PartsLink24 busca pieza %r (pedido %r)", term, query)
        rows = await _run_part_search(page, term)
        scored = _rank_rows(rows, query)
        if scored:
            return scored
        last = scored
    return last


async def _click_first(page, locator) -> bool:
    try:
        if await locator.count() == 0:
            return False
        await locator.first.click(force=True)
        return True
    except Exception:
        return False


async def _open_diagram(page, rows: list[dict]) -> bool:
    """Clic en el primer resultado / lámina para abrir el despiece."""
    if not rows:
        return False
    code = str((rows[0] or {}).get("code") or "").strip()
    lamina = str((rows[0] or {}).get("lamina") or (rows[0] or {}).get("note") or "").strip()
    clicks = []
    if lamina:
        clicks.append(page.get_by_text(lamina, exact=False).locator("visible=true"))
    if code:
        clicks.append(page.get_by_text(code, exact=False).locator("visible=true"))
    for loc in clicks:
        if await _click_first(page, loc):
            logger.info("PartsLink24 clic despiece code=%s lamina=%s", code, lamina)
            await page.wait_for_timeout(800)
            return True
    logger.warning("PartsLink24: no pude cliclear un resultado")
    return False


async def _capture_diagram(page, path: Path) -> bool:
    selectors = (
        "canvas",
        "svg",
        '[class*="diagram" i]',
        '[class*="drawing" i]',
        '[class*="illustration" i]',
        '[class*="lamina" i]',
        '[class*="sheet" i]',
        "img",
    )
    min_bytes = 18000
    for _ in range(16):
        best = None
        best_area = 0.0
        for target in (page, *page.frames):
            for selector in selectors:
                try:
                    loc = target.locator(selector).locator("visible=true")
                    count = await loc.count()
                except Exception:
                    continue
                for index in range(min(count, 8)):
                    box = await loc.nth(index).bounding_box()
                    if not box or box["width"] < 220 or box["height"] < 160:
                        continue
                    area = box["width"] * box["height"]
                    if area > best_area:
                        best_area = area
                        best = loc.nth(index)
        if best is None:
            await page.wait_for_timeout(500)
            continue
        await best.screenshot(path=str(path))
        size = path.stat().st_size if path.exists() else 0
        if size >= min_bytes:
            logger.info("PartsLink24 captura %s bytes", size)
            return True
        await page.wait_for_timeout(500)
    size = path.stat().st_size if path.exists() else 0
    logger.warning("PartsLink24 captura chica (%s bytes)", size)
    return False


async def _read_search_list(page) -> list[dict]:
    text = await page.inner_text("body")
    pattern = re.compile(
        r"N[uú]mero de pieza\s*([A-Z0-9][A-Z0-9 ]{6,22})\s*Denominaci[oó]n\s*(.+?)(?=\s*(?:GP|SG|L[aá]mina|N[uú]mero de pieza)|$)",
        re.IGNORECASE | re.DOTALL,
    )
    items: list[dict] = []
    seen: set[str] = set()
    for match in pattern.finditer(text):
        code = " ".join(match.group(1).split())
        name = " ".join(match.group(2).split())
        name = re.sub(r"\s*>>\s*", " ", name).strip(" -")
        if len(name) > 80:
            name = name[:80].rsplit(" ", 1)[0]
        key = f"{code}|{fold(name)}"
        if key in seen:
            continue
        seen.add(key)
        lamina = ""
        rest = text[match.end() : match.end() + 180]
        lamina_hit = re.search(r"L[aá]mina\s*(\d{3}-\d{3})", rest, re.I)
        if lamina_hit:
            lamina = lamina_hit.group(1)
        gp = ""
        gp_hit = re.search(r"\bGP\s*(\d+)", rest, re.I)
        if gp_hit:
            gp = gp_hit.group(1)
        items.append(
            {
                "code": code,
                "name": name,
                "note": "",
                "lamina": lamina,
                "gp": gp,
                "raw": f"{code} {name}",
            }
        )
    return items


async def _read_rows(page) -> list[dict]:
    raw = await page.evaluate(
        """() => {
            const out = [];
            const push = (cells) => {
                const clean = cells.map(c => (c || "").replace(/\\s+/g, " ").trim()).filter(Boolean);
                if (clean.length >= 2) out.push(clean);
            };
            document.querySelectorAll("tr").forEach(tr => {
                push([...tr.querySelectorAll("th,td")].map(c => c.innerText));
            });
            document.querySelectorAll('[role="row"]').forEach(tr => {
                push([...tr.querySelectorAll('[role="cell"], [role="columnheader"], td, th')].map(c => c.innerText));
            });
            return out;
        }"""
    )
    items: list[dict] = []
    seen: set[str] = set()
    for cells in raw:
        blob = " ".join(cells)
        if _header_row(blob):
            continue
        code = _first_part_no(blob)
        name = _best_name(cells, code)
        key = f"{code}|{fold(name)}"
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "code": code,
                "name": name,
                "note": " · ".join(cells[3:6])[:80] if len(cells) > 3 else "",
                "raw": blob[:240],
            }
        )
    return items


def _header_row(blob: str) -> bool:
    text = fold(blob)
    headers = ("denominacion", "numero de pieza", "grupo principal", "subgrupo", "lamina")
    return sum(1 for word in headers if word in text) >= 2


def _first_part_no(blob: str) -> str:
    match = _PART_NO.search(blob.upper())
    return match.group(0).strip() if match else ""


def _best_name(cells: list[str], code: str) -> str:
    skip = fold(code)
    for cell in cells:
        text = cell.strip()
        if len(text) < 3 or fold(text) == skip:
            continue
        if _PART_NO.fullmatch(text.replace("  ", " ")):
            continue
        if text.isdigit():
            continue
        return text[:80]
    return ""


_PUMP_EXCLUDE = {
    "agua": (
        "combustible",
        "gasolina",
        "gasoil",
        "vacio",
        "aceite",
        "inyector",
        "deflector",
        "lavafaros",
        "limpiaparabrisas",
        "direccion",
        "hidraulic",
        "servo",
    ),
    "combustible": (
        "refriger",
        "aceite",
        "vacio",
        "inyector",
        "deflector",
        "direccion",
        "hidraulic",
    ),
    "aceite": (
        "refriger",
        "combustible",
        "vacio",
        "inyector",
        "deflector",
        "agua",
        "direccion",
    ),
    "direccion": (
        "refriger",
        "combustible",
        "aceite",
        "vacio",
        "inyector",
        "deflector",
        "agua",
    ),
    "vacio": (
        "refriger",
        "combustible",
        "aceite",
        "inyector",
        "deflector",
        "agua",
        "direccion",
    ),
    "inyector": (
        "refriger",
        "combustible",
        "aceite",
        "vacio",
        "deflector",
        "agua",
        "direccion",
    ),
}
_PUMP_REQUIRE = {
    "agua": ("refriger", "agua"),
    "combustible": ("combustible", "gasolina", "gasoil"),
    "aceite": ("aceite",),
    "direccion": ("direccion", "hidraulic", "servo"),
    "vacio": ("vacio",),
    "inyector": ("inyector",),
}


def _item_blob(item: dict) -> str:
    return fold(
        " ".join(str(item.get(key) or "") for key in ("code", "name", "note", "raw"))
    )


def _rank_pump_rows(rows: list[dict], kind: str) -> list[dict]:
    exclude = _PUMP_EXCLUDE.get(kind, ())
    require = _PUMP_REQUIRE.get(kind, ())
    scored: list[tuple[int, dict]] = []
    for item in rows:
        blob = _item_blob(item)
        if any(word in blob for word in exclude):
            continue
        if kind == "agua" and "deflector" in blob:
            continue
        marks = sum(1 for word in require if word in blob)
        has_pump = "bomba" in blob or "pump" in blob
        if kind == "agua":
            if not marks and not has_pump:
                continue
            score = marks * 4 + (2 if has_pump else 0)
            scored.append((score, item))
            continue
        if not marks:
            continue
        scored.append((marks + (1 if has_pump else 0), item))
    if kind == "agua":
        strong = [(score, item) for score, item in scored if score >= 4]
        scored = strong or [(score, item) for score, item in scored if score > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored][:8]


def _rank_rows(rows: list[dict], query: str) -> list[dict]:
    kind = pump_kind_wanted(query)
    if kind:
        return _rank_pump_rows(rows, kind)
    tokens = [token for token in fold(query).split() if len(token) > 2]
    if not tokens:
        return []
    scored: list[tuple[int, dict]] = []
    for item in rows:
        blob = _item_blob(item)
        hits = sum(
            1
            for token in tokens
            if token in blob or any(stem in blob for stem in _stems([token]))
        )
        if not hits:
            continue
        if len(tokens) >= 2 and hits < len(tokens):
            continue
        scored.append((hits, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored][:8]


_ACCESSORY = (
    "tope",
    "tensor",
    "reten",
    "junta",
    "tornillo",
    "tuerca",
    "fuelle",
    "soporte",
    "elemento tensor",
)


def _narrow_rows(rows: list[dict], query: str) -> tuple[list[dict], str]:
    """Saca accesorios y pide eje/lado si hay varias familias (ej. todos los amortiguadores)."""
    wanted = fold(query)
    cleaned = []
    for item in rows:
        name = fold(str(item.get("name") or ""))
        if any(word in name for word in _ACCESSORY) and not any(
            word in wanted for word in _ACCESSORY
        ):
            continue
        cleaned.append(item)
    cleaned = _dedupe_codes(cleaned)

    axle = axle_wanted(query)
    if axle:
        filtered = [item for item in cleaned if _axle_of(item) in {"", axle} or _axle_of(item) == axle]
        strict = [item for item in cleaned if _axle_of(item) == axle]
        cleaned = strict or filtered
    elif needs_axle_clarify(query):
        axles = { _axle_of(item) for item in cleaned if _axle_of(item) }
        if len(axles) > 1:
            return [], "delantera o trasera"

    side = side_wanted(query)
    if side:
        strict = [item for item in cleaned if _side_of(item) == side]
        if strict:
            cleaned = strict
    elif needs_side_clarify(query):
        sides = { _side_of(item) for item in cleaned if _side_of(item) }
        if len(sides) > 1:
            return [], "izquierda o derecha"

    variant = _pump_variant_ask(cleaned, query)
    if variant:
        return [], variant

    return cleaned[:5], ""


def _pump_variant_ask(rows: list[dict], query: str) -> str:
    """Si hay bomba de agua completa y también solo el impulsor, preguntar."""
    if pump_kind_wanted(query) != "agua" or len(rows) < 2:
        return ""
    blobs = [fold(str(item.get("name") or "")) for item in rows]
    housing = any("carcasa" in blob or "completa" in blob for blob in blobs)
    impeller = any("impulsor" in blob or "rodete" in blob for blob in blobs)
    if housing and impeller:
        return "completa con carcasa o solo el impulsor"
    return ""


def _dedupe_codes(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in rows:
        code = str(item.get("code") or "").strip()
        if code and code in seen:
            continue
        if code:
            seen.add(code)
        out.append(item)
    return out


def _axle_of(item: dict) -> str:
    gp = str(item.get("gp") or "")
    lamina = str(item.get("lamina") or "")
    blob = fold(" ".join(str(item.get(k) or "") for k in ("name", "raw", "note")))
    if gp == "4" or lamina.startswith("41") or "delanter" in blob:
        return "delantero"
    if gp == "5" or lamina.startswith("51") or "traser" in blob:
        return "trasero"
    return ""


def _side_of(item: dict) -> str:
    blob = fold(str(item.get("name") or ""))
    if "izquierd" in blob:
        return "izquierdo"
    if "derech" in blob:
        return "derecho"
    return ""


def _stems(tokens: list[str]) -> set[str]:
    out: set[str] = set()
    for token in tokens:
        out.add(token)
        if token.endswith("es") and len(token) > 5:
            out.add(token[:-2])
        elif token.endswith("s") and len(token) > 4:
            out.add(token[:-1])
        else:
            out.add(token + "s")
            out.add(token + "es")
    return out


async def lookup_reply(
    chasis: str,
    query: str,
    screenshot_to: str | None = None,
    brand: str = "",
    model: str = "",
) -> str:
    try:
        data = await lookup(
            chasis, query, screenshot_to=screenshot_to, brand=brand, model=model
        )
    except PartsLinkError as exc:
        logger.warning("PartsLink24: %s", exc)
        detail = str(exc)
        if "no se asignó" in detail or "no abrió el catálogo" in detail:
            where = f" en {brand}" if brand else ""
            return (
                f"Entré al catálogo Peugeot de PartsLink y {chasis} no aparece "
                "(Acceso directo no encontró el auto). "
                "Ese número de 8 no alcanza: pasame los 17 del parabrisas o de la cédula. "
                "Si no, lo mira un vendedor."
            )
        return (
            f"No pude consultar el catálogo ahora. "
            f"Dejo el chasis {chasis} para que lo mire un vendedor."
        )
    except Exception:
        logger.exception("PartsLink24 inesperado")
        return (
            f"No pude consultar el catálogo ahora. "
            f"Dejo el chasis {chasis} para que lo mire un vendedor."
        )
    return format_results(
        chasis,
        str(data.get("vehicle") or ""),
        list(data.get("rows") or []),
        ask=str(data.get("ask") or ""),
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Probar PartsLink24 sin WhatsApp")
    parser.add_argument("--chasis", required=True)
    parser.add_argument("--q", required=True)
    parser.add_argument("--brand", default="peugeot")
    parser.add_argument("--model", default="")
    parser.add_argument("--shot", help="Guardar captura del despiece en este path")
    args = parser.parse_args()
    print(
        asyncio.run(
            lookup_reply(
                args.chasis,
                args.q,
                screenshot_to=args.shot,
                brand=args.brand,
                model=args.model,
            )
        )
    )
