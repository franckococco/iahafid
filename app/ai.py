import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_GEMINI_MODELS = (
    "gemini-3.6-flash",
    "gemini-flash-latest",
    "gemini-3.5-flash",
)


async def reply_to(
    user_text: str,
    history: list[dict] | None = None,
    extra_context: str = "",
) -> str:
    mode = settings.ai_mode.strip().lower()
    if mode == "echo":
        return f"IAHAF recibió: {user_text}"
    if mode in {"openai", "gemini"}:
        if _use_gemini():
            return await _gemini_reply(user_text, history or [], extra_context)
        return await _openai_reply(user_text, history or [], extra_context)
    raise ValueError(f"AI_MODE desconocido: {settings.ai_mode}")


def _use_gemini() -> bool:
    base = settings.openai_base_url.lower()
    model = settings.openai_model.lower()
    return "generativelanguage.googleapis.com" in base or model.startswith("gemini")


def _system_prompt(extra_context: str) -> str:
    if not extra_context.strip():
        return settings.ai_system_prompt
    return (
        f"{settings.ai_system_prompt}\n\n"
        "Información interna para esta consulta (no la copies de forma literal si no hace falta):\n"
        f"{extra_context}"
    )


async def _openai_reply(user_text: str, history: list[dict], extra_context: str) -> str:
    if not settings.openai_api_key:
        return "Falta OPENAI_API_KEY en el archivo .env"

    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    messages = [{"role": "system", "content": _system_prompt(extra_context)}]
    for turn in history:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": turn.get("text", "")})
    messages.append({"role": "user", "content": user_text})
    payload = {
        "model": settings.openai_model,
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 500,
    }
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code >= 400:
            logger.error("AI request failed: %s %s", response.status_code, response.text[:500])
            return "Tuve un problema para generar la respuesta. Probá de nuevo en un momento."
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


async def _gemini_reply(user_text: str, history: list[dict], extra_context: str) -> str:
    if not settings.openai_api_key:
        return "Falta OPENAI_API_KEY en el archivo .env"

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.openai_api_key)
    preferred = settings.openai_model.strip()

    contents: list[types.Content] = []
    for turn in history:
        role = "model" if turn.get("role") == "assistant" else "user"
        contents.append(
            types.Content(role=role, parts=[types.Part(text=turn.get("text", ""))])
        )
    contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))

    last_error = ""
    configs = [
        types.GenerateContentConfig(
            system_instruction=_system_prompt(extra_context),
            temperature=0.3,
            max_output_tokens=1024,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
        types.GenerateContentConfig(
            system_instruction=_system_prompt(extra_context),
            temperature=0.3,
            max_output_tokens=1024,
        ),
    ]
    models = []
    if preferred:
        models.append(preferred)
    for name in _GEMINI_MODELS:
        if name not in models:
            models.append(name)
    for model in models:
        for config in configs:
            try:
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                text = (response.text or "").strip()
                if text:
                    logger.info("Gemini OK with model %s", model)
                    return text
            except Exception as exc:
                last_error = str(exc)[:400]
                logger.warning("Gemini model %s failed: %s", model, last_error)
                continue

    logger.error("Gemini SDK failed: %s", last_error)
    return "Tuve un problema para generar la respuesta. Probá de nuevo en un momento."
