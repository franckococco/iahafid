import hashlib
import hmac
import json
import logging
from collections import OrderedDict

from fastapi import FastAPI, HTTPException, Query, Request, Response

from app.ai import reply_to
from app.config import settings
from app.whatsapp import mark_as_read, send_text

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
    try:
        await _handle_payload(payload)
    except Exception:
        logger.exception("Error procesando webhook")
    # Siempre 200: si Meta recibe error, reintenta el mismo evento.
    return {"status": "ok"}


async def _handle_payload(payload: dict) -> None:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []) or []:
                await _handle_message(message)


async def _handle_message(message: dict) -> None:
    message_id = message.get("id")
    sender = message.get("from")
    msg_type = message.get("type")

    if not message_id or not sender:
        return
    if _already_seen(message_id):
        logger.info("Mensaje duplicado ignorado: %s", message_id)
        return

    await mark_as_read(message_id)

    user_id = message.get("from_user_id") or ""
    if msg_type != "text":
        await send_text(sender, "Por ahora solo puedo leer mensajes de texto.", user_id)
        return

    text = (message.get("text") or {}).get("body", "").strip()
    if not text:
        return

    logger.info("De %s: %s", sender, text)
    answer = await reply_to(text)
    await send_text(sender, answer, user_id)
