import asyncio
import hashlib
import hmac
import html as html_lib
import json
import logging
import time
from collections import OrderedDict
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.ai import history_for_ai, phrase, reply_to
from app.catalog import (
    fallback_quote,
    find_products,
    is_complex,
    remember_match,
    search_manuals,
    search_products,
)
from app.config import _ROOT, settings
from app.memory import append as remember
from app.memory import (
    clear_conversation,
    history_for,
    list_handoffs,
    mark_handoff_seen,
    profile_for,
    set_profile,
)
from app.sales import (
    ASK_CHASSIS_REPLY,
    GOT_CHASSIS_ONLY,
    RESET_REPLY,
    NEED_DETAILS,
    GREET_REPLY,
    greet_reply,
    with_hello,
    daypart,
    chassis_context,
    extract_chassis,
    handoff_reply,
    last_piece_query,
    local_quote_ok,
    piece_query,
    brand_hint,
    model_hint,
    motor_hint,
    named_vehicle,
    peugeot_drill_spec,
    ask_motor_reply,
    oem_family,
    is_motor_clarify,
    is_position_only,
    is_clarify_only,
    merge_piece,
    piece_clarify_ask,
    is_greeting_only,
    fold,
    wants_human,
    wants_photo,
    wants_reset,
    is_sendable,
    SAFE_FALLBACK,
)
from app.whatsapp import mark_as_read, notify_operator, send_image, send_text
from app.partslink import enabled as partslink_enabled
from app.partslink import short_vehicle_spec
from app.oem import listed_has_parts, listed_unique_part, lookup_reply
from app import expoyer, infobal, servicebox
from app.learn import list_asks, remember_ask, remember_reply, similar_replies

_AI_FAILS = "Tuve un problema para generar la respuesta."
_MAX_MESSAGE_AGE = 10 * 60
_turn: dict[str, int] = {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="IAHAF WhatsApp")

# Meta a veces reenvía el mismo webhook. Guardamos IDs recientes para no contestar dos veces.
_seen_ids: OrderedDict[str, None] = OrderedDict()
_MAX_SEEN = 500


def _already_seen(message_id: str) -> bool:
    if message_id in _seen_ids:
        return True
    _seen_ids[message_id] = None
    while len(_seen_ids) > _MAX_SEEN:
        _seen_ids.popitem(last=False)
    return False


def _can_lookup(marca: str, modelo: str, chasis: str) -> bool:
    if oem_family(marca, modelo, chasis) == "vw":
        return partslink_enabled()
    return infobal.enabled() or servicebox.enabled() or expoyer.enabled()


def _next_turn(sender: str) -> int:
    """Cada mensaje vivo anula búsquedas de catálogo que todavía no terminaron."""
    n = _turn.get(sender, 0) + 1
    _turn[sender] = n
    return n


def _still_this_turn(sender: str, gen: int) -> bool:
    return _turn.get(sender) == gen


def _message_too_old(message: dict) -> bool:
    """Meta reenvía webhooks que el túnel no contestó; no hay que atenderlos horas después."""
    raw = message.get("timestamp")
    try:
        sent = int(raw)
    except (TypeError, ValueError):
        return False
    if sent <= 0:
        return False
    return (time.time() - sent) > _MAX_MESSAGE_AGE


def _forget_shot(shot) -> None:
    """No reenviar un despiece de otra consulta si esta búsqueda falló."""
    try:
        shot.unlink(missing_ok=True)
    except OSError:
        pass


async def _send_despiece(sender: str, shot, listed: str, user_id: str) -> bool:
    """Manda la lámina si ya está. Varios códigos: igual se envía; el círculo es una opción."""
    if not shot.exists():
        return False
    caption = (
        "En el despiece está marcada con el círculo."
        if listed_unique_part(listed)
        else "Este es el despiece. El círculo marca una de las opciones del listado."
    )
    return await send_image(sender, shot, caption, user_id)


def _needs_motor_ask(chasis: str, marca: str, modelo: str, hints: dict) -> bool:
    if oem_family(marca, modelo, chasis) == "psa":
        return False
    if not chasis or len(chasis) >= 17:
        return False
    if marca and marca not in {"peugeot", "citroen"}:
        return False
    if short_vehicle_spec(chasis):
        return False
    if hints.get("litros") and hints.get("fuel"):
        return False
    return True


def _vehicle_spec(chasis: str, modelo: str, hints: dict) -> dict | None:
    known = short_vehicle_spec(chasis)
    if known:
        return known
    return peugeot_drill_spec(modelo, hints)


def _valid_signature(raw_body: bytes, header: str | None) -> bool:
    if not settings.whatsapp_app_secret:
        logger.warning("WHATSAPP_APP_SECRET vacío: se acepta el webhook sin verificar firma")
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.whatsapp_app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    received = header.split("=", 1)[1]
    return hmac.compare_digest(expected, received)


async def _gemini_or_fallback(text: str, extra: str, fallback: str, sender: str) -> str:
    extra = (
        f"Hora en el mostrador: {daypart()}. "
        "Si es el primer mensaje del pedido, saludá breve con eso; si ya venís hablando, no lo repitas. "
        "Hablá como vendedor de mostrador, no como formulario.\n"
        f"{extra}"
    )
    answer = await reply_to(
        text,
        history=history_for_ai(history_for(sender)),
        extra_context=extra,
    )
    if answer.startswith(_AI_FAILS) or not is_sendable(answer):
        logger.warning("Gemini no sirvió; uso plantilla")
        return fallback
    return answer


def _local_page() -> str:
    pending = [item for item in list_handoffs() if not item.get("visto")]
    rows = []
    for item in list_handoffs()[:40]:
        visto = bool(item.get("visto"))
        cliente = html_lib.escape(str(item.get("cliente") or ""))
        pieza = html_lib.escape(str(item.get("pieza") or "-"))
        chasis = html_lib.escape(str(item.get("chasis") or "-"))
        dijo = html_lib.escape(str(item.get("dijo") or "-"))
        when = html_lib.escape(str(item.get("at") or "")[:19].replace("T", " "))
        btn = ""
        if not visto:
            at = quote(str(item.get("at") or ""), safe="")
            btn = f'<p><a href="/local/visto?at={html_lib.escape(at, quote=True)}">Ya lo tomé</a></p>'
        tone = "pendiente" if not visto else "visto"
        rows.append(
            f'<article class="{tone}"><p><b>{when}</b> · {cliente}</p>'
            f"<p>Pieza: {pieza}<br>Chasis: {chasis}<br>Dijo: {dijo}</p>"
            f"{btn}</article>"
        )
    body = "".join(rows) or "<p>No hay consultas derivadas.</p>"
    learned = []
    for item in list_asks(25):
        pieza = html_lib.escape(str(item.get("pieza") or " ".join(item.get("keys") or [])))
        last = html_lib.escape(str(item.get("last") or "-"))
        hits = html_lib.escape(str(item.get("hits") or 1))
        estado = "encontró" if item.get("found") else "no figuró"
        learned.append(
            f'<article class="visto"><p><b>{pieza}</b> · {hits} vez · {estado}</p>'
            f"<p>Dijo: {last}</p></article>"
        )
    asks = "".join(learned) or "<p>Todavía no hay pedidos guardados.</p>"
    title = f"Local IAHAF ({len(pending)} en espera)"
    return f"""<!doctype html>
<html lang="es"><head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="8">
<title>{html_lib.escape(title)}</title>
<style>
body{{font-family:sans-serif;max-width:40rem;margin:1.5rem auto;padding:0 1rem;background:#111;color:#eee}}
h1{{font-size:1.2rem}}
h2{{font-size:1rem;margin-top:2rem}}
.pendiente{{border:1px solid #e6b800;background:#2a2408;padding:0.8rem;margin:0.8rem 0}}
.visto{{opacity:0.85;border:1px solid #444;padding:0.8rem;margin:0.8rem 0}}
button{{padding:0.4rem 0.8rem}}
</style></head>
<body>
<h1>{html_lib.escape(title)}</h1>
<p>Dejá esta pestaña abierta en la PC del local. Cuando el bot deriva, aparece acá. Si hay un celular distinto en OPERATOR_WHATSAPP, también le llega un WhatsApp.</p>
{body}
<h2>Cómo piden (el bot aprende el tono y las palabras)</h2>
{asks}
</body></html>"""


@app.get("/health")
async def health():
    return {"ok": True, "ai_mode": settings.ai_mode}


@app.get("/local", response_class=HTMLResponse)
async def local_board():
    """Pantalla del local: consultas que el bot dejó para un vendedor."""
    return HTMLResponse(_local_page())


@app.get("/local/visto")
async def local_seen(at: str = Query(default="")):
    mark_handoff_seen(at)
    return RedirectResponse("/local", status_code=303)


@app.get("/consulta")
async def consulta(q: str = Query(default="")):
    """Consulta el catálogo grabado (productos + lo aprendido de chats)."""
    return {"q": q, "productos": find_products(q)}


@app.get("/partslink")
async def partslink_consulta(
    chasis: str = Query(default=""),
    q: str = Query(default=""),
    brand: str = Query(default="peugeot"),
    token: str = Query(default=""),
):
    """Prueba local: /partslink?chasis=...&q=amortiguadores&token=iahaf-verify-cambiar"""
    if token != settings.whatsapp_verify_token:
        raise HTTPException(status_code=403, detail="Token inválido")
    if not partslink_enabled():
        raise HTTPException(status_code=503, detail="PartsLink24 no está configurado")
    if not chasis or not q:
        raise HTTPException(status_code=400, detail="Faltan chasis y q")
    from app.partslink import lookup

    return await lookup(chasis, q, brand=brand)


@app.get("/webhook")
async def verify_webhook(
    mode: str = Query(alias="hub.mode", default=""),
    token: str = Query(alias="hub.verify_token", default=""),
    challenge: str = Query(alias="hub.challenge", default=""),
):
    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verificación de webhook rechazada")


@app.post("/webhook")
async def receive_webhook(request: Request):
    raw = await request.body()
    logger.info("POST /webhook (%s bytes) %s", len(raw), raw[:800])
    if not _valid_signature(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=403, detail="Firma inválida")

    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON inválido")
    asyncio.create_task(_handle_payload(payload))
    return {"status": "ok"}


async def _handle_payload(payload: dict) -> None:
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for message in value.get("messages", []) or []:
                    try:
                        await _handle_message(message)
                    except Exception:
                        logger.exception("Error en mensaje")
                        sender = message.get("from")
                        if sender:
                            await send_text(
                                sender,
                                SAFE_FALLBACK,
                                message.get("from_user_id") or "",
                            )
    except Exception:
        logger.exception("Error procesando webhook")


async def _handle_message(message: dict) -> None:
    message_id = message.get("id")
    sender = message.get("from")
    msg_type = message.get("type")

    if not message_id or not sender:
        return
    if _already_seen(message_id):
        logger.info("Mensaje duplicado ignorado: %s", message_id)
        return
    if _message_too_old(message):
        logger.info("Mensaje viejo ignorado id=%s ts=%s", message_id, message.get("timestamp"))
        return

    user_id = message.get("from_user_id") or ""
    if msg_type != "text":
        await send_text(sender, "Por ahora solo puedo leer mensajes de texto.", user_id)
        return

    text = (message.get("text") or {}).get("body", "").strip()
    if not text:
        return

    gen = _next_turn(sender)
    logger.info("De %s: %s", sender, text)
    asyncio.create_task(mark_as_read(message_id))

    if wants_reset(text):
        clear_conversation(sender)
        remember(sender, "user", text)
        remember(sender, "assistant", RESET_REPLY)
        await send_text(sender, RESET_REPLY, user_id)
        return

    if is_greeting_only(text):
        clear_conversation(sender)
        extra = (
            "HECHOS: el cliente SOLO saludó; todavía no pidió una pieza.\n"
            f"Hora en el mostrador: {daypart()}. "
            "Saludá con Buenos días / Buenas tardes / Buenas noches según esa hora. "
            "Cálido, breve, de vos. No pidas chasis. No hagas formulario. "
            "Podés invitarlo a decir la pieza y el auto cuando quiera."
        )
        answer = await _gemini_or_fallback(text, extra, greet_reply(), sender)
        if not is_sendable(answer):
            answer = greet_reply()
        remember(sender, "user", text)
        remember(sender, "assistant", answer)
        await send_text(sender, answer, user_id)
        return

    found_chassis = extract_chassis(text)
    previous = str(profile_for(sender).get("chasis") or "")
    if found_chassis and previous and found_chassis != previous:
        clear_conversation(sender)
        logger.info("Chasis distinto: se cierra el pedido anterior")
    if found_chassis:
        set_profile(sender, chasis=found_chassis)
        logger.info("Chasis de %s: %s", sender, found_chassis)
    past_user = [
        item["text"] for item in history_for(sender) if item.get("role") == "user"
    ]
    chassis_in_chat = found_chassis or next(
        (extract_chassis(msg) for msg in reversed(past_user) if extract_chassis(msg)),
        "",
    )
    chasis = chassis_in_chat or ""
    named_brand, _ = named_vehicle(*past_user, text)
    if chasis and named_brand:
        if oem_family(named_brand, "", "") != oem_family("", "", chasis):
            logger.info("Chasis de otro auto; lo descarto")
            chasis = ""

    past_msgs = [
        item["text"] for item in history_for(sender) if item.get("role") == "user"
    ]
    lookup = f"{' '.join(past_msgs)} {text}".strip()
    matches = find_products(lookup)
    remember_match(text, matches)
    pieza = last_piece_query(past_msgs, text, chasis)
    stored = str(profile_for(sender).get("pieza") or "")
    extra = piece_query(text, chasis)
    if wants_photo(text):
        pieza = stored or last_piece_query(past_msgs, "", chasis)
    elif extra and is_motor_clarify(extra):
        pieza = stored or last_piece_query(past_msgs, "", chasis)
    elif extra and stored and (is_position_only(extra) or is_clarify_only(extra)):
        pieza = merge_piece(stored, extra)
    if pieza:
        logger.info("Pieza a buscar: %s", pieza)

    marca = brand_hint(*past_msgs, text)
    if marca:
        set_profile(sender, marca=marca)
        logger.info("Marca de %s: %s", sender, marca)
    marca = marca or str(profile_for(sender).get("marca") or "")
    if chasis and len(chasis) < 17 and not marca:
        marca = "peugeot"
        logger.info("Chasis corto: pruebo catálogo Peugeot")
    modelo = model_hint(*past_msgs, text)
    if modelo:
        set_profile(sender, modelo=modelo)
        logger.info("Modelo de %s: %s", sender, modelo)
    modelo = modelo or str(profile_for(sender).get("modelo") or "")

    profile = profile_for(sender)
    hints = motor_hint(
        text,
        *past_msgs,
        str(profile.get("litros") or ""),
        str(profile.get("fuel") or ""),
    )
    if hints.get("litros"):
        set_profile(sender, litros=str(hints["litros"]))
    if hints.get("fuel"):
        set_profile(sender, fuel=str(hints["fuel"]))
    spec = _vehicle_spec(chasis, modelo, hints)

    shot = _ROOT / "data" / "shots" / f"{sender}.png"
    answer = ""

    if wants_photo(text):
        if shot.exists() and chasis:
            sent = await _send_despiece(sender, shot, "", user_id)
            answer = "Ahí te mandé el despiece." if sent else "No pude adjuntar la foto. Decime de nuevo."
        elif chasis and pieza and _can_lookup(marca, modelo, chasis):
            if _needs_motor_ask(chasis, marca, modelo, hints):
                answer = ask_motor_reply(modelo, hints)
            else:
                await send_text(
                    sender,
                    "Dame un segundo, estoy en el catálogo.",
                    user_id,
                    check=False,
                )
                answer = await lookup_reply(
                    chasis,
                    pieza,
                    screenshot_to=str(shot) if oem_family(marca, modelo, chasis) == "vw" else None,
                    brand=marca,
                    model=modelo,
                    spec=spec,
                )
                if not _still_this_turn(sender, gen):
                    logger.info("Descarto despiece tarde de %s", sender)
                    return
                sent = await _send_despiece(sender, shot, answer, user_id)
                if not answer:
                    answer = "Ahí te mandé el despiece." if sent else "No pude sacar la foto del despiece."
        else:
            answer = "Primero el chasis y la pieza, después te marco la foto."
    elif wants_human(text):
        answer = handoff_reply(chasis)
    elif local_quote_ok(matches, lookup):
        extra = (
            search_products(lookup)
            + "\n\n"
            + chassis_context(chasis)
            + "\n\n"
            + search_manuals(lookup)
            + "\n\n"
            + similar_replies(text, "quote")
        )
        answer = await _gemini_or_fallback(
            text,
            extra,
            fallback_quote(lookup) or ASK_CHASSIS_REPLY,
            sender,
        )
        if is_sendable(answer) and not answer.startswith(_AI_FAILS):
            remember_reply("quote", text, answer)
    elif pieza and not chasis:
        set_profile(sender, pieza=pieza, marca=marca, modelo=modelo)
        remember_ask(text, pieza, found=False, chasis="")
        answer = await phrase(
            text,
            "Pedí el chasis de la cédula o el parabrisas, no el de motor.",
            "chassis",
            with_hello(ASK_CHASSIS_REPLY),
            history_for_ai(history_for(sender)),
        )
    elif chasis and not pieza:
        answer = await phrase(
            text,
            "Anoté el chasis. Pedí qué pieza busca.",
            "got_chassis",
            GOT_CHASSIS_ONLY,
            history_for_ai(history_for(sender)),
        )
    elif chasis and pieza and _can_lookup(marca, modelo, chasis):
        pending = piece_clarify_ask(pieza)
        set_profile(sender, chasis=chasis, pieza=pieza, marca=marca, modelo=modelo)
        if pending:
            answer = f"¿La pieza es {pending}?"
        elif _needs_motor_ask(chasis, marca, modelo, hints):
            answer = ask_motor_reply(modelo, hints)
        else:
            _forget_shot(shot)
            await send_text(
                sender,
                "Dame un segundo, estoy en el catálogo.",
                user_id,
                check=False,
            )
            listed = await lookup_reply(
                chasis,
                pieza,
                screenshot_to=None,
                brand=marca,
                model=modelo,
                spec=spec,
            )
            if not _still_this_turn(sender, gen):
                logger.info("Descarto catálogo tarde de %s", sender)
                return
            remember_ask(text, pieza, found=listed_has_parts(listed), chasis=chasis)
            facts = listed
            if not listed_has_parts(listed):
                facts += (
                    "\nNo hay código en el catálogo. No inventes ninguno. "
                    "Decile que lo mira un compañero del local."
                )
            answer = await phrase(
                text,
                facts,
                "oem",
                listed,
                history_for_ai(history_for(sender)),
            )
    elif matches and is_complex(matches[0]) and chasis:
        answer = handoff_reply(chasis)
    else:
        extra = (
            search_products(lookup)
            + "\n\n"
            + chassis_context(chasis)
            + "\n\n"
            + search_manuals(lookup)
            + "\n\n"
            + similar_replies(text, "quote")
        )
        answer = await _gemini_or_fallback(
            text,
            extra,
            fallback_quote(lookup) or NEED_DETAILS,
            sender,
        )
        if is_sendable(answer) and not answer.startswith(_AI_FAILS):
            remember_reply("quote", text, answer)

    if not _still_this_turn(sender, gen):
        logger.info("No envío respuesta tarde de %s", sender)
        return

    if not is_sendable(answer) or str(answer).startswith(_AI_FAILS):
        logger.warning("Respuesta inválida, uso plantilla: %s", (answer or "")[:160])
        answer = SAFE_FALLBACK

    remember(sender, "user", text)
    remember(sender, "assistant", answer)
    hard = fold(answer)
    if wants_human(text) or any(
        fold(marker) in hard
        for marker in (
            "te dejo con un vendedor",
            "te dejo con un compañero",
            "lo mira un vendedor",
            "mira un vendedor",
            "hay varias en el catalogo",
            "no pude ubicar",
            "no pude consultar el catalogo",
            "companero del local",
        )
    ):
        await notify_operator(
            "deriva a vendedor",
            sender,
            text,
            chasis=chasis,
            pieza=pieza,
        )
    await send_text(sender, answer, user_id)
