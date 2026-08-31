"""Consulta PartsLink24: el software entra, pega el chasis y lee la tabla. Gemini no busca."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from pathlib import Path

from app.browser import chromium_launch_kwargs
from app.config import _ROOT, settings
from app.sales import (
    axle_wanted,
    catalog_close,
    fold,
    needs_axle_clarify,
    needs_side_clarify,
    pump_kind_wanted,
    search_queries,
    side_wanted,
    _PIECE_STOP,
)

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


def short_vehicle_spec(chasis: str) -> dict:
    """Ficha de un chasis de 8 dígitos si está en la lista del local."""
    return _short_spec(chasis)


def listed_has_parts(listed: str) -> bool:
    """True si esta consulta trajo códigos o ítems de catálogo."""
    blob = fold(listed or "")
    if "aparece:" not in blob:
        return False
    if blob.startswith("para el chasis"):
        return True
    return any(name in blob for name in ("infobal", "expoyer", "service box"))


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
    shown = rows[:5]
    for item in shown:
        code = item.get("code") or ""
        name = item.get("name") or ""
        extra = item.get("note") or ""
        piece = " — ".join(part for part in (code, name) if part)
        if extra and extra not in piece:
            piece = f"{piece} ({extra})"
        lines.append(f"- {piece}")
    lines.append(catalog_close(len(rows)))
    lines.append("Otro auto o pieza: *nuevo pedido*.")
    return "\n".join(lines)


async def lookup(
    chasis: str,
    query: str,
    screenshot_to: str | None = None,
    brand: str = "",
    model: str = "",
    spec: dict | None = None,
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
            spec or {},
        )


async def _lookup_locked(
    chasis: str,
    query: str,
    screenshot_to: str | None = None,
    brand: str = "",
    model: str = "",
    spec: dict | None = None,
) -> dict:
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(**chromium_launch_kwargs())
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
        vehicle = await _search_chassis(
            page, chasis, brand=brand, model=model, spec=spec or {}
        )
        rows = await _search_parts(page, query)
        rows, ask = _narrow_rows(rows, query)
        if screenshot_to and rows and not ask:
            path = Path(screenshot_to)
            path.parent.mkdir(parents=True, exist_ok=True)
            opened = await _open_diagram(page, rows)
            captured = False
            if opened:
                await _select_part(page, rows[0])
                captured = await _capture_diagram(page, path)
            if captured:
                marked = await _mark_part_on_shot(page, path)
                logger.info("PartsLink24 despiece en %s marcado=%s", path, marked)
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
    await _submit_login(
        page,
        settings.partslink24_company_id,
        settings.partslink24_user,
        settings.partslink24_password,
    )
    try:
        await _chassis_box(page).first.wait_for(state="visible", timeout=30000)
    except Exception as exc:
        raise PartsLinkError("No pude entrar a PartsLink24. Revisá usuario y clave.") from exc


async def _submit_login(page, company_id: str, username: str, password_value: str) -> None:
    company = page.locator('[data-test-id="pl24-login-ui-loginForm-input-companyId"]').locator("visible=true")
    user = page.locator('[data-test-id="pl24-login-ui-loginForm-input-username"]').locator("visible=true")
    password = page.locator('[data-test-id="pl24-login-ui-loginForm-input-password"]').locator("visible=true")
    if await company.count() == 0:
        company = page.locator('input[name="companyId"]').locator("visible=true")
        user = page.locator('input[name="username"]').locator("visible=true")
        password = page.locator('input[type="password"]').locator("visible=true")
    await company.first.fill(company_id)
    await user.first.fill(username)
    await password.first.fill(password_value)
    button = page.get_by_role("button", name=re.compile(r"iniciar sesi[oó]n|log in", re.I)).locator("visible=true")
    await button.first.click()
    confirm = page.get_by_role("button", name=re.compile(r"^confirmar$", re.I))
    try:
        await confirm.first.wait_for(state="visible", timeout=8000)
        await confirm.first.click()
        logger.info("PartsLink24: confirmé reemplazar la sesión abierta")
    except Exception:
        logger.info("PartsLink24: no pidió confirmar sesión")


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


async def _search_chassis(
    page,
    chasis: str,
    brand: str = "",
    model: str = "",
    spec: dict | None = None,
) -> str:
    short = 8 <= len(chasis) < 17
    brands: list[str] = []
    if brand:
        brands.append(brand)
    elif short:
        brands.append("peugeot")
    ficha = _short_spec(chasis) or dict(spec or {})
    if short:
        for name in brands:
            await _dismiss_dialogs(page)
            if not await _already_in_brand(page, name):
                await _open_brand_catalog(page, name)
            await _dismiss_dialogs(page)
            if not await _already_in_brand(page, name):
                logger.warning("PartsLink24: no entré al catálogo %s", name)
                continue
            if ficha:
                if await _drill_known_vehicle(page, ficha):
                    label = " ".join(
                        part
                        for part in (
                            ficha.get("modelo") or model,
                            ficha.get("anio"),
                            "AMLAT" if ficha.get("amlat") else "",
                            ficha.get("carroceria"),
                            ficha.get("motor"),
                        )
                        if part
                    )
                    return label.strip() or chasis
                logger.warning("PartsLink24: no pude armar el auto de la ficha %s", chasis)
            known = bool(_short_spec(chasis))
            if known or not ficha:
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
    terms = search_queries(query)
    if not pump_kind_wanted(query):
        terms = terms[:4]
    for term in terms:
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
            await page.wait_for_timeout(1600)
            return True
    logger.warning("PartsLink24: no pude cliclear un resultado")
    return False


async def _select_part(page, row: dict) -> None:
    """Vuelve a cliclear el código para que el catálogo resalte esa pieza."""
    code = str((row or {}).get("code") or "").strip()
    if not code:
        return
    loc = page.get_by_text(code, exact=False).locator("visible=true")
    if await _click_first(page, loc):
        await page.wait_for_timeout(1200)


async def _find_diagram(page):
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
    return best


async def _capture_diagram(page, path: Path) -> bool:
    min_bytes = 18000
    for _ in range(16):
        best = await _find_diagram(page)
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


_JS_HIGHLIGHT = """() => {
    const tooBig = (r) => r.width > 420 || r.height > 420;
    const tooSmall = (r) => r.width < 8 || r.height < 8;
    const hits = [];
    const push = (el) => {
        const r = el.getBoundingClientRect();
        if (tooSmall(r) || tooBig(r) || r.x < 0 || r.y < 0) return;
        hits.push({x: r.x, y: r.y, w: r.width, h: r.height});
    };
    document.querySelectorAll(
        '[class*="selected" i], [class*="highlight" i], [class*="hotspot" i], [aria-selected="true"]'
    ).forEach(push);
    document.querySelectorAll("svg circle, svg ellipse, svg path, svg g").forEach((el) => {
        const stroke = (el.getAttribute("stroke") || "").toLowerCase();
        const style = (el.getAttribute("style") || "").toLowerCase();
        const blob = stroke + style;
        if (/#f|#e|red|orange|#ff|rgb\\(\\s*2[0-9]{2}/.test(blob)) push(el);
    });
    hits.sort((a, b) => a.w * a.h - b.w * b.h);
    return hits[0] || null;
}"""


async def _mark_part_on_shot(page, path: Path) -> bool:
    """Círculo sobre la pieza resaltada en el despiece."""
    diagram = await _find_diagram(page)
    mark = await _dom_highlight_center(page, diagram, path)
    if mark is None:
        mark = _color_highlight_center(path)
    if mark is None:
        logger.warning("PartsLink24: no ubiqué el hotspot para el círculo")
        return False
    cx, cy, radius = mark
    _paint_circle(path, cx, cy, radius)
    logger.info("PartsLink24 círculo en (%.0f, %.0f) r=%.0f", cx, cy, radius)
    return True


async def _dom_highlight_center(page, diagram, img_path: Path) -> tuple[float, float, float] | None:
    if diagram is None or not img_path.exists():
        return None
    box = await diagram.bounding_box()
    if not box:
        return None
    hit = None
    for target in (page, *page.frames):
        try:
            found = await target.evaluate(_JS_HIGHLIGHT)
        except Exception:
            continue
        if found:
            hit = found
            break
    if not hit:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    with Image.open(img_path) as image:
        iw, ih = image.size
    sx = iw / max(box["width"], 1)
    sy = ih / max(box["height"], 1)
    cx = (hit["x"] + hit["w"] / 2 - box["x"]) * sx
    cy = (hit["y"] + hit["h"] / 2 - box["y"]) * sy
    if not (0 <= cx <= iw and 0 <= cy <= ih):
        return None
    radius = max(hit["w"], hit["h"]) * max(sx, sy) * 0.55 + 16
    return cx, cy, radius


def _color_highlight_center(path: Path) -> tuple[float, float, float] | None:
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Falta Pillow para marcar el despiece")
        return None
    if not path.exists():
        return None
    image = Image.open(path).convert("RGB")
    width, height = image.size
    pixels = image.load()
    xs: list[int] = []
    ys: list[int] = []
    step = 2 if width * height > 400_000 else 1
    for y in range(0, height, step):
        for x in range(0, width, step):
            red, green, blue = pixels[x, y]
            mx, mn = max(red, green, blue), min(red, green, blue)
            if mx < 90 or mx - mn < 55:
                continue
            is_red = red > green + 25 and red > blue + 25 and red > 140
            is_blue = blue > red + 25 and blue > green + 15 and blue > 140
            is_yellow = red > 180 and green > 150 and blue < 120
            if is_red or is_blue or is_yellow:
                xs.append(x)
                ys.append(y)
    if len(xs) < 18:
        return None
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    near_x = [x for x, y in zip(xs, ys) if abs(x - cx) + abs(y - cy) < 200]
    near_y = [y for x, y in zip(xs, ys) if abs(x - cx) + abs(y - cy) < 200]
    if len(near_x) < 10:
        near_x, near_y = xs, ys
    radius = max(max(near_x) - min(near_x), max(near_y) - min(near_y)) * 0.55 + 18
    if radius > min(width, height) * 0.28:
        radius = min(width, height) * 0.12
    return cx, cy, radius


def _paint_circle(path: Path, cx: float, cy: float, radius: float) -> None:
    from PIL import Image, ImageDraw

    image = Image.open(path).convert("RGB")
    draw = ImageDraw.Draw(image)
    limit = min(image.size) * 0.22
    radius = max(28.0, min(float(radius), limit))
    for width, color in ((8, (255, 255, 255)), (5, (220, 20, 20))):
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            outline=color,
            width=width,
        )
    image.save(path, "PNG")


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


def _piece_subject(name: str) -> str:
    """Primera palabra de la pieza, no un verbo ni 'para/de'."""
    skip = _PIECE_STOP | {"con", "por", "al", "y", "que", "como"}
    text = fold(name)
    for ch in "()[]/.,-;:":
        text = text.replace(ch, " ")
    words = [word for word in text.split() if len(word) > 2 and word not in skip]
    for word in words:
        if word in _SUBJECT_ALIASES:
            return word
    return words[0] if words else ""


_SUBJECT_ALIASES = {
    "radiador": {"radiador", "radiator", "refrigerante", "coolant"},
    "radiator": {"radiador", "radiator", "refrigerante", "coolant"},
    "ventilador": {"ventilador", "electroventilador", "electro"},
    "electroventilador": {"ventilador", "electroventilador", "electro"},
    "faro": {"faro", "optica", "piloto", "farol"},
    "optica": {"faro", "optica", "piloto", "farol"},
    "piloto": {"faro", "optica", "piloto", "farol"},
    "amortiguador": {"amortiguador", "amort"},
    "bomba": {"bomba", "pump"},
    "filtro": {"filtro", "filter"},
    "tablero": {"tablero", "cuadro", "instrumentos", "cluster", "kombi", "kombiinstrument"},
    "cuadro": {"tablero", "cuadro", "instrumentos", "cluster", "kombi"},
    "manguera": {"manguera", "manguito", "hose", "schlauch", "tubo", "flexible"},
    "manguito": {"manguera", "manguito", "hose", "schlauch", "tubo", "flexible"},
    "embrague": {"embrague", "clutch", "kupplung"},
    "freno": {"freno", "brake", "bremse"},
}

_SATELLITES = {
    "radiador": (
        "persiana",
        "ventilador",
        "electroventilador",
        "caja",
        "contacto",
        "manguito",
        "sensor",
        "tapa",
        "tapon",
        "deposito",
        "expansion",
        "vaso",
    ),
}


def _subject_aliases(word: str) -> set[str]:
    if not word:
        return set()
    return _SUBJECT_ALIASES.get(word, {word})


def _item_is_primary(item: dict, query: str) -> bool:
    """El nombre ES la pieza pedida, no un accesorio que la menciona."""
    wanted = _piece_subject(query)
    if not wanted:
        return True
    subject = _piece_subject(str(item.get("name") or ""))
    return subject in _subject_aliases(wanted)


_CLUTCH_MARK = ("embrague", "clutch", "kupplung", "presion")
_BRAKE_MARK = ("freno", "brake", "bremse")


def _wrong_disc_family(item: dict, query: str) -> bool:
    """Disco de embrague ≠ disco de freno."""
    wanted = fold(query)
    name = fold(str(item.get("name") or ""))
    if "disco" not in wanted:
        return False
    want_clutch = any(word in wanted for word in ("embrague", "clutch", "ebrage"))
    want_brake = any(word in wanted for word in ("freno", "brake"))
    has_clutch = any(word in name for word in _CLUTCH_MARK)
    has_brake = any(word in name for word in _BRAKE_MARK)
    if want_clutch and not want_brake:
        return (has_brake and not has_clutch) or not has_clutch
    if want_brake and not want_clutch:
        return (has_clutch and not has_brake) or not has_brake
    return False


def _wrong_family(item: dict, query: str) -> bool:
    return _wrong_radiator_family(item, query) or _wrong_disc_family(item, query)


def _wrong_radiator_family(item: dict, query: str) -> bool:
    wanted = fold(query)
    name = fold(str(item.get("name") or ""))
    if "radiador" not in wanted:
        return False
    want_oil = "aceite" in wanted
    has_oil = "aceite" in name
    if want_oil and not has_oil:
        return True
    if not want_oil and has_oil:
        return True
    return False


def _is_satellite(item: dict, query: str) -> bool:
    wanted = _piece_subject(query)
    if not wanted:
        return False
    asked = fold(query)
    name = fold(str(item.get("name") or ""))
    subject = _piece_subject(str(item.get("name") or ""))
    for word in _SATELLITES.get(wanted, ()):
        if word in asked:
            continue
        if subject == word or word in name:
            return True
    return False


def _keep_asked_piece(rows: list[dict], query: str) -> list[dict]:
    """Si pidieron radiador, queda el radiador; no el ventilador ni la persiana."""
    kept = [item for item in rows if not _wrong_family(item, query)]
    primary = [item for item in kept if _item_is_primary(item, query)]
    if primary:
        return primary
    without_sat = [item for item in kept if not _is_satellite(item, query)]
    return without_sat or kept


def _is_pump_article(item: dict) -> bool:
    subject = _piece_subject(str(item.get("name") or ""))
    return subject in {"bomba", "pump", "impulsor", "rodete"}


def _rank_pump_rows(rows: list[dict], kind: str) -> list[dict]:
    exclude = _PUMP_EXCLUDE.get(kind, ())
    require = _PUMP_REQUIRE.get(kind, ())
    scored: list[tuple[int, dict]] = []
    for item in rows:
        if not _is_pump_article(item):
            continue
        name = fold(str(item.get("name") or ""))
        blob = _item_blob(item)
        if any(word in blob for word in exclude):
            continue
        if kind == "agua" and "deflector" in name:
            continue
        marks = sum(1 for word in require if word in name or word in blob)
        if kind == "agua" and not marks:
            continue
        if not marks:
            continue
        scored.append((marks, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored][:8]


_HOSE_EXCLUDE = (
    "centrado",
    "sincronizador",
    "desplazable",
    "embrague",
    "marcha",
)


def _hose_wants_coolant(query: str) -> bool:
    blob = fold(query)
    hose = any(word in blob for word in ("manguera", "manguito", "tubo", "hose"))
    coolant = any(word in blob for word in ("radiador", "refriger", "coolant"))
    return hose and coolant


def _is_coolant_line(item: dict) -> bool:
    blob = _item_blob(item)
    if any(word in blob for word in _HOSE_EXCLUDE):
        return False
    return any(
        word in blob
        for word in (
            "radiador",
            "radiator",
            "refriger",
            "coolant",
            "kuehl",
            "kuhl",
            "wasser",
        )
    )


def _token_in_blob(token: str, blob: str) -> bool:
    aliases = _subject_aliases(token) | _stems([token])
    aliases.add(token)
    return any(word in blob for word in aliases if word and len(word) > 2)


def _rank_rows(rows: list[dict], query: str) -> list[dict]:
    kind = pump_kind_wanted(query)
    if kind:
        return _rank_pump_rows(rows, kind)
    tokens = [token for token in fold(query).split() if len(token) > 2]
    if not tokens:
        return []
    wanted = _piece_subject(query)
    scored: list[tuple[int, dict]] = []
    for item in rows:
        blob = _item_blob(item)
        hits = sum(1 for token in tokens if _token_in_blob(token, blob))
        if not hits:
            continue
        if _hose_wants_coolant(query) and not _is_coolant_line(item):
            continue
        if wanted and not _token_in_blob(wanted, blob):
            continue
        if _wrong_family(item, query):
            continue
        if _item_is_primary(item, query):
            hits += 10
        elif _is_satellite(item, query):
            hits -= 5
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

    cleaned = _keep_asked_piece(cleaned, query)
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
    spec: dict | None = None,
) -> str:
    try:
        data = await lookup(
            chasis,
            query,
            screenshot_to=screenshot_to,
            brand=brand,
            model=model,
            spec=spec,
        )
    except PartsLinkError as exc:
        logger.warning("PartsLink24: %s", exc)
        detail = str(exc)
        if "no se asignó" in detail or "no abrió el catálogo" in detail:
            if spec:
                label = " ".join(
                    part
                    for part in (
                        str(spec.get("modelo") or "").strip(),
                        str(spec.get("motor") or "").strip(),
                    )
                    if part
                )
                return (
                    f"Entré al catálogo Peugeot y no pude armar el auto"
                    f"{(' ' + label) if label else ''} con el chasis {chasis}. "
                    "Pasame los 17 de la cédula o el parabrisas, o lo mira un vendedor."
                )
            return (
                f"Anoté el chasis {chasis}, pero con esos 8 dígitos no abre el auto en el catálogo. "
                "Decime si es 1.4 o 1.6, nafta o diesel, y te busco la pieza. "
                "Si tenés los 17 de la cédula o el parabrisas, mejor."
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
