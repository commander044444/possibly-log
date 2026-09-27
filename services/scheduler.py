"""
Central async news scheduler.
Respects FREE/VIP feature limits (interval, daily cap). No per-channel loops.
"""
from __future__ import annotations

import asyncio
import random
import logging
from typing import Optional

import database as db
from services import news as news_svc
from services import subscription as sub_svc
from utils.helpers import utcnow
import config

logger = logging.getLogger(__name__)


class NewsScheduler:
    def __init__(self, bot):
        self.bot = bot
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_publish: dict = {}
        self._lock = asyncio.Lock()

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="news-scheduler")
        logger.info("News scheduler started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("News scheduler stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scheduler tick failed — continuing")
            await asyncio.sleep(config.SCHEDULER_TICK_SECONDS)

    async def _tick(self) -> None:
        try:
            n = await news_svc.fetch_from_sources()
            if n:
                logger.info("Fetched %s new news items", n)
        except Exception:
            logger.exception("fetch_from_sources failed")

        channels = await db.fetch(
            """
            SELECT c.* FROM channels c
            WHERE c.is_active = TRUE AND c.status = 'active'
            """
        )
        for ch in channels:
            try:
                await self._process_channel(dict(ch))
            except Exception:
                logger.exception("process channel %s failed", ch["channel_id"])
                continue

    async def _process_channel(self, ch: dict) -> None:
        channel_id = ch["channel_id"]
        owner_id = ch["owner_user_id"]

        if await sub_svc.is_banned(owner_id):
            await db.execute(
                "UPDATE channels SET is_active = FALSE, status = 'stopped' WHERE channel_id = $1",
                channel_id,
            )
            return

        limits = await sub_svc.get_user_limits(owner_id)
        if limits["tier"] == "BANNED":
            return

        # enforce min interval from plan limits
        # FREE: random gap between 30–50 minutes each cycle
        if limits["tier"] == "FREE":
            lo = int(getattr(config, "FREE_MIN_NEWS_INTERVAL_MINUTES", 30))
            hi = int(getattr(config, "FREE_MAX_NEWS_INTERVAL_MINUTES", 50))
            if hi < lo:
                hi = lo
            interval_min = random.randint(lo, hi)
        else:
            interval_min = max(
                int(ch.get("news_interval") or limits["min_interval_minutes"]),
                int(limits["min_interval_minutes"]),
            )
        last = self._last_publish.get(channel_id)
        now = utcnow()
        if last and (now - last).total_seconds() < interval_min * 60:
            return

        # daily publish limit (FREE)
        ok_day, reason = await sub_svc.can_publish_today(owner_id)
        if not ok_day:
            logger.info("Daily limit for user %s: skip channel %s", owner_id, channel_id)
            return

        cats = await db.fetch(
            "SELECT category_key FROM channel_categories WHERE channel_id = $1",
            channel_id,
        )
        cat_keys = [r["category_key"] for r in cats]
        if not cat_keys:
            return

        # FREE: only free categories if mixed
        if limits["tier"] == "FREE":
            cat_keys = [k for k in cat_keys if k in config.FREE_CATEGORIES]
            if not cat_keys:
                return

        items = await news_svc.get_unpublished_for_channel(channel_id, cat_keys, limit=1)
        if not items:
            return

        news = items[0]
        ok = await news_svc.mark_published(channel_id, news["id"])
        if not ok:
            return

        text = news_svc.format_news_message(news)
        try:
            try:
                await self.bot.send_message(chat_id=channel_id, text=text)
            except Exception as send_err:
                uname = ch.get("channel_username")
                if uname:
                    try:
                        await self.bot.send_message(chat_id=f"@{uname.lstrip('@')}", text=text)
                    except Exception:
                        raise send_err
                else:
                    raise send_err
            await news_svc.bump_channel_stats(channel_id, "text")
            await sub_svc.increment_daily_publish(owner_id)
            self._last_publish[channel_id] = now
            await asyncio.sleep(config.NEWS_PUBLISH_DELAY)
        except Exception as e:
            logger.warning("publish to %s failed: %s", channel_id, e)
