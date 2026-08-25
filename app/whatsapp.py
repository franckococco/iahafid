import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GRAPH_URL = f"https://graph.facebook.com/{settings.graph_api_version}"


def recipient_candidates(to: str, user_id: str = "") -> list[str]:
    candidates: list[str] = []
    for value in (to, user_id, *_argentine_alternates(to)):
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


async def send_text(to: str, body: str, user_id: str = "") -> bool:
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
                return True
            last_error = response.text
            logger.warning("WhatsApp send %s failed: %s", recipient, response.text[:400])
        logger.error("WhatsApp send failed for all recipients: %s", last_error)
        return False


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
