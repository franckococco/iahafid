import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def reply_to(user_text: str) -> str:
    mode = settings.ai_mode.strip().lower()
    if mode == "echo":
        return f"IAHAF recibió: {user_text}"
    if mode == "openai":
        return await _openai_reply(user_text)
    raise ValueError(f"AI_MODE desconocido: {settings.ai_mode}")


async def _openai_reply(user_text: str) -> str:
    if not settings.openai_api_key:
        return "Falta OPENAI_API_KEY en el archivo .env"

    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.openai_model,
        "messages": [
            {"role": "system", "content": settings.ai_system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.4,
        "max_tokens": 500,
    }
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code >= 400:
            logger.error("AI request failed: %s %s", response.status_code, response.text)
            return "Tuve un problema para generar la respuesta. Probá de nuevo en un momento."
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
