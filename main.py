"""
Bale News Management Bot — entrypoint.
Railway-compatible: worker process runs this file.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from bale import Bot, Message, CallbackQuery

import config
import database as db
from handlers import user as user_handlers
from services.scheduler import NewsScheduler
from services.news import close_http_session

# ─── Logging ───────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format=config.LOG_FORMAT,
    stream=sys.stdout,
)
# never log secrets
logging.getLogger("asyncio").setLevel(logging.WARNING)
logger = logging.getLogger("main")


def create_bot() -> Bot:
    if not config.BOT_TOKEN or config.BOT_TOKEN == "PUT_BOT_TOKEN_HERE":
        logger.error("Set BOT_TOKEN in config.py before running.")
        sys.exit(1)
    return Bot(token=config.BOT_TOKEN)


async def on_startup(bot: Bot, scheduler: NewsScheduler) -> None:
    logger.info("Initializing database…")
    await db.init_db()
    scheduler.start()
    logger.info("Bot ready. Admin ID=%s", config.ADMIN_ID)


async def on_shutdown(scheduler: NewsScheduler) -> None:
    logger.info("Shutting down…")
    await scheduler.stop()
    await close_http_session()
    await db.close_db()


def main() -> None:
    bot = create_bot()
    scheduler = NewsScheduler(bot)

    @bot.event
    async def on_ready():
        try:
            await on_startup(bot, scheduler)
            me = bot.user
            logger.info("Logged in as %s", getattr(me, "username", me))
        except Exception:
            logger.exception("Startup failed")
            raise

    @bot.event
    async def on_message(message: Message):
        try:
            # ignore channel posts from bot itself if needed
            await user_handlers.handle_text_message(message, bot)
        except Exception:
            logger.exception("on_message error")

    @bot.event
    async def on_callback(callback: CallbackQuery):
        try:
            await user_handlers.handle_callback(callback, bot)
        except Exception:
            logger.exception("on_callback error")

    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(on_shutdown(scheduler))
            else:
                loop.run_until_complete(on_shutdown(scheduler))
        except Exception:
            logger.exception("Shutdown error")


if __name__ == "__main__":
    main()
