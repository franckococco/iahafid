import logging

import httpx

from app.config import settings
from app.sales import SAFE_FALLBACK, is_sendable

logger = logging.getLogger(__name__)

GRAPH_URL = f"https://graph.facebook.com/{settings.graph_api_version}"


_working_recipients: dict[str, str] = {}


def recipient_candidates(to: str, user_id: str = "") -> list[str]:
    cached = _working_recipients.get(to)
    candidates: list[str] = []
    for value in (cached, *_argentine_alternates(to), to, user_id):
        if value and value not in candidates:
            candidates.append(value)
    return candidates


def _argentine_alternates(wa_id: str) -> list[str]:
    if not wa_id.startswith("549") or len(wa_id) < 12:
        return []
    rest = wa_id[3:]
    alts: list[str] = []
    # Interior: 549 + área (3) + local (6-8) → 54 + área + 15 + local
    if len(rest) >= 9:
        alts.append(f"54{rest[:3]}15{rest[3:]}")
        alts.append(f"54{rest}")
    # Buenos Aires: 54911 + 8 dígitos → 5411 15 + 8 dígitos
    if rest.startswith("11") and len(rest) >= 10:
        alts.append(f"541115{rest[2:]}")
    return alts


async def send_text(to: str, body: str, user_id: str = "", *, check: bool = True) -> bool:
    if check and not is_sendable(body):
        logger.error("Bloqueé mensaje interno/cortado: %s", (body or "")[:160])
        body = SAFE_FALLBACK
    url = f"{GRAPH_URL}/{settings.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        last_error = ""
        for recipient in recipient_candidates(to, user_id):
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": recipient,
                "type": "text",
                "text": {"preview_url": False, "body": body[:4096]},
            }
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code < 400:
                logger.info("WhatsApp send OK to %s", recipient)
                _working_recipients[to] = recipient
                return True
            last_error = response.text
            logger.warning("WhatsApp send %s failed: %s", recipient, response.text[:400])
        logger.error("WhatsApp send failed for all recipients: %s", last_error)
        return False


async def send_image(to: str, path, caption: str = "", user_id: str = "") -> bool:
    from pathlib import Path

    image = Path(path)
    if not image.exists():
        logger.warning("No hay imagen para enviar: %s", image)
        return False
    media_id = await _upload_media(image)
    if not media_id:
        return False
    url = f"{GRAPH_URL}/{settings.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        for recipient in recipient_candidates(to, user_id):
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": recipient,
                "type": "image",
                "image": {"id": media_id, "caption": caption[:1024]},
            }
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code < 400:
                logger.info("WhatsApp image OK to %s", recipient)
                _working_recipients[to] = recipient
                return True
            logger.warning("WhatsApp image %s failed: %s", recipient, response.text[:400])
    return False


async def _upload_media(path) -> str:
    url = f"{GRAPH_URL}/{settings.whatsapp_phone_number_id}/media"
    headers = {"Authorization": f"Bearer {settings.whatsapp_token}"}
    mime = "image/png" if str(path).lower().endswith(".png") else "image/jpeg"
    async with httpx.AsyncClient(timeout=60) as client:
        with path.open("rb") as handle:
            response = await client.post(
                url,
                headers=headers,
                data={"messaging_product": "whatsapp", "type": mime},
                files={"file": (path.name, handle, mime)},
            )
        if response.status_code >= 400:
            logger.error("WhatsApp media upload failed: %s", response.text[:400])
            return ""
        return str(response.json().get("id") or "")


async def mark_as_read(message_id: str) -> None:
    url = f"{GRAPH_URL}/{settings.whatsapp_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code >= 400:
            logger.warning("Could not mark as read: %s", response.text)


async def notify_operator(
    reason: str,
    sender: str,
    text: str,
    chasis: str = "",
    pieza: str = "",
) -> None:
    dest = (settings.operator_whatsapp or "").strip()
    if not dest:
        logger.warning("Consulta difícil sin OPERATOR_WHATSAPP (%s)", reason)
        return
    if dest == sender or dest in recipient_candidates(sender):
        return
    body = (
        f"Consulta difícil: {reason}\n"
        f"Cliente: {sender}\n"
        f"Chasis: {chasis or '-'}\n"
        f"Pieza: {pieza or '-'}\n"
        f"Dijo: {text[:400]}"
    )
    await send_text(dest, body)
