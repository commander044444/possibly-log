"""
Channel moderation settings (VIP feature).

IMPORTANT — python-bale-bot 2.5.0 / Bale public Bot API limits:
- Full comment-thread moderation (delete arbitrary user comments under
  channel posts) is NOT reliably exposed the same way as Telegram.
- Bot can delete messages it has permission for in groups/channels where
  it is admin, via Message.delete() / Bot.delete_message when applicable.
- Do NOT fake delete/ban APIs that are not available.

This module stores settings and evaluates messages when the bot receives
them in a context it can act on. Hooks can be extended when Bale expands API.
"""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from typing import Optional, Tuple

import database as db
import config

logger = logging.getLogger(__name__)

# in-memory flood windows (channel_id, user_id) -> timestamps
_flood_buckets: dict = defaultdict(list)


async def get_settings(channel_id: int) -> dict:
    row = await db.fetchrow(
        "SELECT * FROM channel_settings WHERE channel_id = $1", channel_id
    )
    if not row:
        return {
            "anti_profanity": False,
            "anti_link": False,
            "anti_long_message": False,
            "max_message_length": config.DEFAULT_MAX_MESSAGE_LENGTH,
            "anti_flood": False,
            "flood_limit": config.DEFAULT_FLOOD_LIMIT,
            "flood_window": config.DEFAULT_FLOOD_WINDOW,
            "rules_text": None,
        }
    return dict(row)


async def load_banned_words() -> list:
    rows = await db.fetch("SELECT word FROM banned_words")
    return [r["word"].lower() for r in rows]


def _has_link(text: str) -> bool:
    return bool(re.search(r"https?://|t\.me/|ble\.ir/|www\.", text, re.I))


async def evaluate_message(
    channel_id: int,
    user_id: int,
    text: str,
) -> Tuple[bool, Optional[str]]:
    """
    Returns (should_delete, reason).
    Caller must only delete if Bot has real permission in that chat.
    """
    if not text:
        return False, None
    settings = await get_settings(channel_id)

    if settings.get("anti_long_message"):
        limit = settings.get("max_message_length") or config.DEFAULT_MAX_MESSAGE_LENGTH
        if len(text) > limit:
            return True, "long_message"

    if settings.get("anti_link") and _has_link(text):
        return True, "link"

    if settings.get("anti_profanity"):
        words = await load_banned_words()
        lower = text.lower()
        for w in words:
            if w and w in lower:
                return True, "profanity"

    if settings.get("anti_flood"):
        key = (channel_id, user_id)
        now = time.time()
        window = settings.get("flood_window") or config.DEFAULT_FLOOD_WINDOW
        limit = settings.get("flood_limit") or config.DEFAULT_FLOOD_LIMIT
        bucket = [t for t in _flood_buckets[key] if now - t < window]
        bucket.append(now)
        _flood_buckets[key] = bucket
        if len(bucket) > limit:
            return True, "flood"

    return False, None


async def log_moderation(
    channel_id: int,
    user_id: int,
    action: str,
    reason: str,
    preview: str = "",
) -> None:
    await db.execute(
        """
        INSERT INTO moderation_logs (channel_id, user_id, action, reason, message_preview)
        VALUES ($1, $2, $3, $4, $5)
        """,
        channel_id, user_id, action, reason, (preview or "")[:200],
    )
