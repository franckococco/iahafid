"""Consulta PartsLink24: el software entra, pega el chasis y lee la tabla. Gemini no busca."""

from __future__ import annotations

import asyncio
import logging
import re

from pathlib import Path

from app.config import _ROOT, settings
from app.sales import fold

logger = logging.getLogger(__name__)

_STATE = _ROOT / "data" / "partslink-state.json"
_DEBUG = _ROOT / "data" / "partslink-debug.png"
_LOCK = asyncio.Lock()

_PART_NO = re.compile(
    r"\b[A-Z0-9]{2,3}\s?[A-Z0-9]{3}\s?[A-Z0-9]{3}(?:\s?[A-Z0-9])?\b",
    re.IGNORECASE,
)


class PartsLinkError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(
        settings.partslink24_enabled
        and settings.partslink24_company_id
        and settings.partslink24_user
        and settings.partslink24_password
    )


def format_results(chasis: str, vehicle: str, rows: list[dict]) -> str:
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


async def lookup(chasis: str, query: str, screenshot_to: str | None = None) -> dict:
    """Devuelve vehicle + filas de la tabla. No inventa precios."""
    if not enabled():
        raise PartsLinkError("Faltan las claves de PartsLink24 en el .env")
    if not chasis or not query:
        raise PartsLinkError("Hace falta chasis y pieza")
    async with _LOCK:
        return await _lookup_locked(
            chasis.strip().upper(), query.strip(), screenshot_to
        )


async def _lookup_locked(chasis: str, query: str, screenshot_to: str | None = None) -> dict:
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
        vehicle = await _search_chassis(page, chasis)
        rows = await _search_parts(page, query)
        if screenshot_to:
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
        return {"vehicle": vehicle, "rows": rows}
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
    return page.get_by_placeholder(re.compile(r"n[uú]mero de chasis|chassis", re.I))


def _parts_box(page):
    return page.get_by_placeholder(re.compile(r"buscar piezas|search parts", re.I))


async def _search_chassis(page, chasis: str) -> str:
    box = _chassis_box(page)
    if await box.count() == 0:
        raise PartsLinkError("No encontré el campo de chasis")
    await box.first.fill("")
    await box.first.fill(chasis)
    await box.first.press("Enter")
    try:
        await _parts_box(page).first.wait_for(state="visible", timeout=30000)
    except Exception:
        await page.wait_for_timeout(2500)
    if await _parts_box(page).count() == 0:
        raise PartsLinkError("El chasis no abrió el catálogo del auto")
    return await _vehicle_name(page)


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


async def _search_parts(page, query: str) -> list[dict]:
    box = _parts_box(page)
    if await box.count() == 0:
        raise PartsLinkError("No encontré 'Buscar piezas' después del chasis")
    logger.info("PartsLink24 busca pieza %r", query)
    await box.first.click()
    await box.first.fill("")
    await box.first.fill(query)
    await page.wait_for_timeout(800)
    await box.first.press("Enter")
    await page.wait_for_timeout(2500)
    rows = await _read_search_list(page)
    if not rows:
        rows = await _read_rows(page)
    scored = _rank_rows(rows, query)
    if scored:
        return scored
    suggestion = page.get_by_text(re.compile(query.split()[0], re.I)).locator("visible=true")
    if await suggestion.count() > 1:
        await suggestion.nth(1).click(force=True)
        await page.wait_for_timeout(2500)
        rows = await _read_search_list(page) or await _read_rows(page)
        scored = _rank_rows(rows, query)
    return scored


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
        items.append(
            {
                "code": code,
                "name": name,
                "note": "",
                "lamina": lamina,
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


def _rank_rows(rows: list[dict], query: str) -> list[dict]:
    tokens = [token for token in fold(query).split() if len(token) > 2]
    if not tokens:
        return []
    stems = _stems(tokens)
    scored: list[tuple[int, dict]] = []
    for item in rows:
        name = fold(str(item.get("name") or ""))
        blob = fold(" ".join(str(v) for v in (item.get("code"), item.get("name"), item.get("note"))))
        if not any(stem in name or stem in blob for stem in stems):
            continue
        score = sum(1 for token in tokens if token in blob or any(s in blob for s in _stems([token])))
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored][:8]


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
    chasis: str, query: str, screenshot_to: str | None = None
) -> str:
    try:
        data = await lookup(chasis, query, screenshot_to=screenshot_to)
    except PartsLinkError as exc:
        logger.warning("PartsLink24: %s", exc)
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
    return format_results(chasis, str(data.get("vehicle") or ""), list(data.get("rows") or []))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Probar PartsLink24 sin WhatsApp")
    parser.add_argument("--chasis", required=True)
    parser.add_argument("--q", required=True)
    parser.add_argument("--shot", help="Guardar captura del despiece en este path")
    args = parser.parse_args()
    print(asyncio.run(lookup_reply(args.chasis, args.q, screenshot_to=args.shot)))
