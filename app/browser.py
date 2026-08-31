"""Playwright: en la PC usa .playwright-browsers; en Railway, el Chromium de la imagen."""

from __future__ import annotations

import os
from pathlib import Path

from app.config import _ROOT

_LOCAL = _ROOT / ".playwright-browsers"
if _LOCAL.exists() and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_LOCAL)


def in_container() -> bool:
    return Path("/.dockerenv").exists() or bool(os.environ.get("RAILWAY_ENVIRONMENT"))


def chromium_launch_kwargs() -> dict:
    args = ["--disable-dev-shm-usage", "--disable-gpu"]
    if in_container():
        args.append("--no-sandbox")
    return {"headless": True, "args": args}
