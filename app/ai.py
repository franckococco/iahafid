import asyncio
import logging

import httpx

from app.config import settings
from app.learn import keeps_oem_codes, remember_reply, similar_replies
from app.sales import is_sendable

logger = logging.getLogger(__name__)

_GEMINI_MODELS = (
    "gemini-3.6-flash",
    "gemini-flash-latest",
    "gemini-3.5-flash",
)
_FAIL = "Tuve un problema para generar la respuesta."
_GEMINI_SECONDS = 12


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
            try:
                text = await asyncio.wait_for(
                    _gemini_reply(user_text, history or [], extra_context),
                    timeout=_GEMINI_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning("Gemini tardó más de %ss; uso plantilla", _GEMINI_SECONDS)
                return _FAIL
            if not is_sendable(text):
                logger.warning("Gemini devolvió texto inválido: %s", text[:160])
                return _FAIL
            return text
        return await _openai_reply(user_text, history or [], extra_context)
    raise ValueError(f"AI_MODE desconocido: {settings.ai_mode}")


async def phrase(
    user_text: str,
    facts: str,
    kind: str,
    fallback: str,
    history: list[dict] | None = None,
) -> str:
    """Gemini arma la frase; si falla o se come un código, usamos la plantilla."""
    examples = similar_replies(user_text, kind)
    extra = (
        f"HECHOS de esta consulta (obligatorios):\n{facts.strip()}\n\n"
        f"{examples}"
    ).strip()
    text = await reply_to(user_text, history=history or [], extra_context=extra)
    if not text or text.startswith(_FAIL) or not is_sendable(text):
        return fallback
    if kind == "oem" and not keeps_oem_codes(text, facts):
        logger.warning("Gemini omitió un código OEM; uso la plantilla")
        return fallback
    remember_reply(kind, user_text, text)
    return text


def history_for_ai(turns: list[dict]) -> list[dict]:
    """No le pasamos a Gemini respuestas cortadas o con reglas internas."""
    clean: list[dict] = []
    for turn in turns:
        text = str(turn.get("text") or "")
        if turn.get("role") == "assistant" and not is_sendable(text):
            continue
        clean.append(turn)
    return clean[-12:]


def _use_gemini() -> bool:
    base = settings.openai_base_url.lower()
    model = settings.openai_model.lower()
    return "generativelanguage.googleapis.com" in base or model.startswith("gemini")


def _system_prompt(extra_context: str) -> str:
    if not extra_context.strip():
        return settings.ai_system_prompt
    return (
        f"{settings.ai_system_prompt}\n\n"
        "Información interna. Los HECHOS mandan; el tono puede ser más de mostrador:\n"
        f"{extra_context}"
    )


async def _openai_reply(user_text: str, history: list[dict], extra_context: str) -> str:
    if not settings.openai_api_key:
        return "Falta OPENAI_API_KEY en el archivo .env"

    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    messages = [{"role": "system", "content": _system_prompt(extra_context)}]
    for turn in history_for_ai(history):
        role = "assistant" if turn.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": turn.get("text", "")})
    messages.append({"role": "user", "content": user_text})
    payload = {
        "model": settings.openai_model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 450,
    }
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code >= 400:
            logger.error("AI request failed: %s %s", response.status_code, response.text[:500])
            return _FAIL
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


def _visible_text(response) -> str:
    try:
        text = (response.text or "").strip()
        if text:
            return text
    except Exception:
        pass
    chunks: list[str] = []
    for cand in getattr(response, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "thought", False):
                continue
            piece = getattr(part, "text", None)
            if piece:
                chunks.append(piece)
    return "".join(chunks).strip()


def _gemini_configs(types, instruction: str):
    configs = []
    thinking = getattr(types, "ThinkingConfig", None)
    afc = types.AutomaticFunctionCallingConfig(disable=True)
    if thinking is not None:
        try:
            configs.append(
                types.GenerateContentConfig(
                    system_instruction=instruction,
                    temperature=0.4,
                    max_output_tokens=2048,
                    thinking_config=thinking(thinking_budget=0),
                    automatic_function_calling=afc,
                )
            )
        except Exception:
            pass
    configs.append(
        types.GenerateContentConfig(
            system_instruction=instruction,
            temperature=0.4,
            max_output_tokens=2048,
            automatic_function_calling=afc,
        )
    )
    configs.append(
        types.GenerateContentConfig(
            system_instruction=instruction,
            temperature=0.4,
            max_output_tokens=2048,
        )
    )
    return configs


async def _gemini_reply(user_text: str, history: list[dict], extra_context: str) -> str:
    if not settings.openai_api_key:
        return "Falta OPENAI_API_KEY en el archivo .env"

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.openai_api_key)
    preferred = settings.openai_model.strip()
    instruction = _system_prompt(extra_context)

    contents: list[types.Content] = []
    for turn in history_for_ai(history):
        role = "model" if turn.get("role") == "assistant" else "user"
        contents.append(
            types.Content(role=role, parts=[types.Part(text=turn.get("text", ""))])
        )
    contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))

    last_error = ""
    models = []
    if preferred:
        models.append(preferred)
    for name in _GEMINI_MODELS:
        if name not in models:
            models.append(name)

    raw_configs = _gemini_configs(types, instruction)
    for model in models:
        for config in raw_configs:
            try:
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                text = _visible_text(response)
                if text:
                    logger.info("Gemini OK with model %s", model)
                    return text
            except Exception as exc:
                last_error = str(exc)[:400]
                logger.warning("Gemini model %s failed: %s", model, last_error)
                continue

    logger.error("Gemini SDK failed: %s", last_error)
    return _FAIL
