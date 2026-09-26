"""
Configuration for Bale News Automation Bot.
No .env — set secrets in this file before deploy.
Primary DB connection: POSTGRESQL_URL (you paste Railway URL here).
"""
from __future__ import annotations

import os
from typing import Dict, Any, List

# ─── Bot ───────────────────────────────────────────────
BOT_TOKEN = "858228563:_gVyZQIjoAy8ZMw0bsG4JRFDWFC9prRnVNc"
ADMIN_ID = 1967315238
ADMIN_USERNAME = "commander04"  # display as @commander04

# ─── PostgreSQL (PRIMARY) ──────────────────────────────
# Paste your Railway PostgreSQL URL here:
POSTGRESQL_URL = "postgresql://postgres:rTzsPViElMQWJWSnYlHLWNWYcQNiwtzl@postgres.railway.internal:5432/railway"

# Fallback only if POSTGRESQL_URL is still the placeholder
_env_db = os.environ.get("DATABASE_URL", "")
if POSTGRESQL_URL in ("", "postgresql://postgres:rTzsPViElMQWJWSnYlHLWNWYcQNiwtzl@postgres.railway.internal:5432/railway") and _env_db:
    POSTGRESQL_URL = _env_db

if POSTGRESQL_URL.startswith("postgres://"):
    POSTGRESQL_URL = POSTGRESQL_URL.replace("postgres://", "postgresql://", 1)

DB_POOL_MIN = 2
DB_POOL_MAX = 10
DB_COMMAND_TIMEOUT = 30

# ─── Payment ───────────────────────────────────────────
CARD_NUMBER = "1928929212929191"
CARD_HOLDER = "test"
PAYMENT_REVIEW_NOTE = (
    "توجه:\n"
    "بررسی درخواست شما ممکن است بین ۲۰ دقیقه تا ۲ ساعت طول بکشد؛ "
    "معمولاً در سریع‌ترین زمان ممکن پاسخگویی انجام می‌شود."
)

# ─── FREE plan limits (defaults; also seeded into system_settings / plans) ─
FREE_MAX_CHANNELS = 1
FREE_MIN_NEWS_INTERVAL_MINUTES = 180  # 3 hours
FREE_MAX_NEWS_PER_DAY = 8
FREE_MAX_SOURCES = 2
FREE_INTERVALS: List[int] = [180, 360, 720, 1440]  # minutes

# ─── VIP interval options (minutes) ────────────────────
VIP_INTERVALS: List[int] = [3, 4, 5, 6, 7, 10, 15, 30, 60]
VIP_DEFAULT_MAX_CHANNELS = 20
VIP_DEFAULT_MIN_INTERVAL = 3
# None = unlimited for daily news / sources when plan has no cap

# ─── Categories (all keys; FREE may use a subset) ──────
CATEGORIES: Dict[str, str] = {
    "iran": "🇮🇷 ایران",
    "world": "🌍 جهان",
    "politics": "🏛 سیاست",
    "economy": "💰 اقتصاد",
    "market": "📈 بازار",
    "currency": "💵 ارز",
    "crypto": "🪙 رمزارز",
    "tech": "💻 تکنولوژی",
    "ai": "🤖 هوش مصنوعی",
    "mobile": "📱 موبایل",
    "computer": "🖥 کامپیوتر",
    "game": "🎮 گیم",
    "football": "⚽ فوتبال",
    "basketball": "🏀 بسکتبال",
    "martial": "🥊 ورزش‌های رزمی",
    "sport": "🏆 ورزش",
    "cinema": "🎬 سینما",
    "tv": "📺 تلویزیون",
    "music": "🎵 موسیقی",
    "culture": "🎨 فرهنگ",
    "science": "🔬 علم",
    "space": "🚀 فضا",
    "weather": "🌦 آب‌وهوا",
    "auto": "🚗 خودرو",
    "aerospace": "✈️ هوافضا",
    "health": "🏥 سلامت",
    "education": "📚 آموزش",
    "incidents": "📰 حوادث",
    "social": "🔍 اجتماعی",
    "internet": "🌐 اینترنت",
    "cybersecurity": "🔐 امنیت سایبری",
    "startup": "💡 استارتاپ",
}

# Categories available on FREE (subset)
FREE_CATEGORIES = [
    "iran", "world", "politics", "economy", "tech", "sport",
    "football", "incidents", "culture", "science",
]

# ─── Scheduler ─────────────────────────────────────────
SCHEDULER_TICK_SECONDS = 30
SOURCE_TIMEOUT = 15
SOURCE_MAX_RETRIES = 2
NEWS_FETCH_LIMIT_PER_SOURCE = 10
NEWS_PUBLISH_DELAY = 0.3
BROADCAST_DELAY = 0.05
USER_COMMAND_COOLDOWN = 1.0

# ─── Moderation defaults ───────────────────────────────
DEFAULT_MAX_MESSAGE_LENGTH = 500
DEFAULT_FLOOD_LIMIT = 5
DEFAULT_FLOOD_WINDOW = 10

# ─── License ───────────────────────────────────────────
LICENSE_LENGTH = 20
LICENSE_EXPIRE_HOURS = 48

# ─── Messages ──────────────────────────────────────────
ABOUT_TEXT = (
    "ℹ️ درباره ما\n\n"
    "این ربات توسط DARKKNIGHT STUDIO توسعه داده شده است.\n\n"
    "👤 سازنده:\n@commander04\n\n"
    "⚔️ تیم:\n@darkknight_studio\n\n"
    "هدف ما ارائه ابزارهای حرفه‌ای برای مدیریت و خودکارسازی "
    "کانال‌های خبری در Bale است."
)

VIP_UPGRADE_TEXT = (
    "👑 این قابلیت مخصوص VIP است.\n\n"
    "برای فعالیت حرفه‌ای و 24/7، اشتراک VIP تهیه کنید."
)

# ─── Logging ───────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
