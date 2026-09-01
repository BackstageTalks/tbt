from __future__ import annotations

import logging

import httpx

from ..config import Settings, settings

logger = logging.getLogger(__name__)


def telegram_message(text: str, cfg: Settings = settings) -> bool:
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        return False
    url = f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage"
    try:
        response = httpx.post(
            url,
            json={"chat_id": cfg.telegram_chat_id, "text": text[:3900]},
            timeout=15,
        )
        response.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        logger.warning("Telegram notification failed: %s", exc)
        return False
