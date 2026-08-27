import asyncio
import hashlib
import hmac
import json
import logging
from collections import OrderedDict

from fastapi import FastAPI, HTTPException, Query, Request, Response

from app.ai import reply_to
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
from app.memory import clear_conversation, history_for, profile_for, set_profile
from app.sales import (
    ASK_CHASSIS_REPLY,
    GOT_CHASSIS_ONLY,
    RESET_REPLY,
    chassis_context,
    extract_chassis,
    handoff_reply,
    last_piece_query,
    local_quote_ok,
    piece_query,
    wants_human,
    wants_photo,
    wants_reset,
)
from app.whatsapp import mark_as_read, send_image, send_text
from app.partslink import enabled as partslink_enabled
from app.partslink import lookup_reply

_AI_FAILS = "Tuve un problema para generar la respuesta."

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


@app.get("/health")
async def health():
    return {"ok": True, "ai_mode": settings.ai_mode}


@app.get("/consulta")
async def consulta(q: str = Query(default="")):
    """Consulta el catálogo grabado (productos + lo aprendido de chats)."""
    return {"q": q, "productos": find_products(q)}


@app.get("/partslink")
async def partslink_consulta(
    chasis: str = Query(default=""),
    q: str = Query(default=""),
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

    return await lookup(chasis, q)


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
                    await _handle_message(message)
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

    user_id = message.get("from_user_id") or ""
    if msg_type != "text":
        await send_text(sender, "Por ahora solo puedo leer mensajes de texto.", user_id)
        return

    text = (message.get("text") or {}).get("body", "").strip()
    if not text:
        return

    logger.info("De %s: %s", sender, text)
    asyncio.create_task(mark_as_read(message_id))

    if wants_reset(text):
        clear_conversation(sender)
        remember(sender, "user", text)
        remember(sender, "assistant", RESET_REPLY)
        await send_text(sender, RESET_REPLY, user_id)
        return

    found_chassis = extract_chassis(text)
    previous = str(profile_for(sender).get("chasis") or "")
    if found_chassis and previous and found_chassis != previous:
        clear_conversation(sender)
        logger.info("Chasis distinto: se cierra el pedido anterior")
    if found_chassis:
        set_profile(sender, chasis=found_chassis)
        logger.info("Chasis de %s: %s", sender, found_chassis)
    chasis = found_chassis or str(profile_for(sender).get("chasis") or "")

    past_msgs = [
        turn["text"] for turn in history_for(sender) if turn.get("role") == "user"
    ]
    lookup = f"{' '.join(past_msgs)} {text}".strip()
    matches = find_products(lookup)
    remember_match(text, matches)
    pieza = last_piece_query(past_msgs, text, chasis)
    stored = str(profile_for(sender).get("pieza") or "")
    if wants_photo(text):
        extra = piece_query(text, chasis)
        pieza = extra or stored or last_piece_query(past_msgs, "", chasis)
    if pieza:
        logger.info("Pieza a buscar: %s", pieza)

    shot = _ROOT / "data" / "shots" / f"{sender}.png"

    if wants_photo(text):
        if chasis and pieza and partslink_enabled():
            await send_text(sender, "Dame un segundo, abro el despiece.", user_id)
            answer = await lookup_reply(chasis, pieza, screenshot_to=str(shot))
            if shot.exists():
                await send_image(sender, shot, "Despiece del catálogo.", user_id)
            else:
                answer = "Ubicé la pieza pero no pude sacar la foto del despiece."
        else:
            answer = "Primero ubicamos la pieza (con el chasis). Después pedime la foto."
    elif wants_human(text):
        answer = handoff_reply(chasis)
    elif local_quote_ok(matches):
        extra = (
            search_products(lookup)
            + "\n\n"
            + chassis_context(chasis)
            + "\n\n"
            + search_manuals(lookup)
        )
        answer = await reply_to(text, history=history_for(sender), extra_context=extra)
        if answer.startswith(_AI_FAILS):
            quote = fallback_quote(lookup)
            if quote:
                logger.warning("Gemini falló; cotizo desde catálogo")
                answer = quote
    elif pieza and not chasis:
        answer = ASK_CHASSIS_REPLY
    elif chasis and not pieza:
        answer = GOT_CHASSIS_ONLY
    elif chasis and pieza and partslink_enabled():
        await send_text(
            sender,
            "Dame un segundo, busco esa pieza por el chasis en el catálogo.",
            user_id,
        )
        answer = await lookup_reply(chasis, pieza)
        set_profile(sender, chasis=chasis, pieza=pieza)
    elif matches and is_complex(matches[0]) and chasis:
        answer = handoff_reply(chasis)
    else:
        extra = (
            search_products(lookup)
            + "\n\n"
            + chassis_context(chasis)
            + "\n\n"
            + search_manuals(lookup)
        )
        answer = await reply_to(text, history=history_for(sender), extra_context=extra)
        if answer.startswith(_AI_FAILS):
            quote = fallback_quote(lookup)
            if quote:
                logger.warning("Gemini falló; cotizo desde catálogo")
                answer = quote

    remember(sender, "user", text)
    remember(sender, "assistant", answer)
    await send_text(sender, answer, user_id)
