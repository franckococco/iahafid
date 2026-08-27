import json
import logging
from pathlib import Path

from app.config import _ROOT

logger = logging.getLogger(__name__)

_PATH = _ROOT / "data" / "chats.json"
_PROFILES = _ROOT / "data" / "customers.json"
_MAX_TURNS = 16


def _load() -> dict:
    if not _PATH.exists():
        return {}
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("chats.json inválido, se reinicia el historial")
        return {}


def _save(data: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def history_for(sender: str) -> list[dict]:
    return list(_load().get(sender, []))


def append(sender: str, role: str, text: str) -> None:
    data = _load()
    turns = data.setdefault(sender, [])
    turns.append({"role": role, "text": text})
    data[sender] = turns[-_MAX_TURNS:]
    _save(data)


def clear_conversation(sender: str) -> None:
    data = _load()
    data[sender] = []
    _save(data)
    profiles = _load_profiles()
    if sender in profiles:
        profiles.pop(sender, None)
        _save_profiles(profiles)
    logger.info("Conversación reiniciada para %s", sender)


def profile_for(sender: str) -> dict:
    return dict(_load_profiles().get(sender) or {})


def set_profile(sender: str, **fields: str) -> dict:
    data = _load_profiles()
    current = dict(data.get(sender) or {})
    for key, value in fields.items():
        if value:
            current[key] = value
    data[sender] = current
    _save_profiles(data)
    return current


def _load_profiles() -> dict:
    if not _PROFILES.exists():
        return {}
    try:
        data = json.loads(_PROFILES.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("customers.json inválido")
        return {}
    return data if isinstance(data, dict) else {}


def _save_profiles(data: dict) -> None:
    _PROFILES.parent.mkdir(parents=True, exist_ok=True)
    _PROFILES.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
