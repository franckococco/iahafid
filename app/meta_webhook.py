"""Pega el Callback URL en Meta por API, sin el panel que Meta suele romper."""

from __future__ import annotations

import logging
import urllib.error
import urllib.request

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_META_DASHBOARD = (
    "https://developers.facebook.com/apps/1810396190374656/dashboard/"
)


def webhook_url(public_base: str) -> str:
    return public_base.rstrip("/") + "/webhook"


def challenge_ok(public_base: str) -> bool:
    """Meta hace GET /webhook?hub.mode=subscribe…; si esto falla, Verify and save también."""
    probe = (
        webhook_url(public_base)
        + "?hub.mode=subscribe&hub.verify_token="
        + settings.whatsapp_verify_token
        + "&hub.challenge=iahaf-ok"
    )
    try:
        with urllib.request.urlopen(probe, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        return "iahaf-ok" in body
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("El túnel no responde el challenge: %s", exc)
        return False


def register_public_webhook(public_base: str) -> tuple[bool, str]:
    """Override del número de prueba. Si anda, no hay que tocar el panel de Meta."""
    if not settings.whatsapp_token or not settings.whatsapp_phone_number_id:
        return False, "Falta token o Phone Number ID en .env"
    if not challenge_ok(public_base):
        return False, "El túnel no responde /webhook; Meta no va a verificar"
    callback = webhook_url(public_base)
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_token}",
        "Content-Type": "application/json",
    }
    graph = f"https://graph.facebook.com/{settings.graph_api_version}"
    payload = {
        "webhook_configuration": {
            "override_callback_uri": callback,
            "verify_token": settings.whatsapp_verify_token,
        }
    }
    try:
        with httpx.Client(timeout=30) as client:
            phone = client.post(
                f"{graph}/{settings.whatsapp_phone_number_id}",
                headers=headers,
                json=payload,
            )
            if phone.status_code < 400 and phone.json().get("success"):
                return True, callback
            waba = settings.whatsapp_business_account_id
            if waba:
                waba_resp = client.post(
                    f"{graph}/{waba}/subscribed_apps",
                    headers=headers,
                    json={
                        "override_callback_uri": callback,
                        "verify_token": settings.whatsapp_verify_token,
                    },
                )
                if waba_resp.status_code < 400 and waba_resp.json().get("success"):
                    return True, callback
                detail = (waba_resp.text or phone.text)[:240]
            else:
                detail = phone.text[:240]
            logger.warning("Meta no aceptó el webhook: %s", detail)
            return False, detail or "Meta rechazó el override"
    except httpx.HTTPError as exc:
        logger.warning("No pude hablar con Graph API: %s", exc)
        return False, str(exc)


def meta_dashboard_url() -> str:
    return _META_DASHBOARD
