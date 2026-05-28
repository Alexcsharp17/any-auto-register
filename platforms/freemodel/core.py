"""FreeModel registration helpers."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse


FREEMODEL_BASE_URL = "https://freemodel.dev"
FREEMODEL_KEYS_URL = f"{FREEMODEL_BASE_URL}/dashboard/keys"
FREEMODEL_DASHBOARD_URL = f"{FREEMODEL_BASE_URL}/dashboard"
FREEMODEL_TELEGRAM_BOT = "FreeModelDevBot"
FREEMODEL_API_BASE = "https://api.freemodel.dev/v1"


def extract_freemodel_start_code(start_link: str) -> str:
    """Return the FreeModel Telegram start token from a t.me or tg:// link."""
    raw = str(start_link or "").strip()
    if not raw:
        raise ValueError("FreeModel Telegram start link is required")

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")
    query = parse_qs(parsed.query)

    if parsed.scheme in {"http", "https"}:
        if host not in {"t.me", "telegram.me"} or path.lower() != FREEMODEL_TELEGRAM_BOT.lower():
            raise ValueError(f"Expected @{FREEMODEL_TELEGRAM_BOT} Telegram link")
        token = (query.get("start") or [""])[0].strip()
    elif parsed.scheme == "tg":
        domain = (query.get("domain") or [""])[0].strip()
        if domain.lower() != FREEMODEL_TELEGRAM_BOT.lower():
            raise ValueError(f"Expected @{FREEMODEL_TELEGRAM_BOT} Telegram link")
        token = (query.get("start") or [""])[0].strip()
    else:
        raise ValueError(f"Unsupported FreeModel Telegram link: {raw}")

    if not token:
        raise ValueError("FreeModel Telegram start token is missing")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        raise ValueError("FreeModel Telegram start token contains unexpected characters")
    return token


def extract_api_key(text: str) -> str:
    """Extract a likely FreeModel API key from visible text or copied JSON."""
    combined = str(text or "")
    patterns = (
        r"\b(fm-[A-Za-z0-9_\-]{16,})\b",
        r"\b(free-[A-Za-z0-9_\-]{16,})\b",
        r"\b(sk-[A-Za-z0-9_\-]{20,})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, combined)
        if match:
            return match.group(1)
    return ""

