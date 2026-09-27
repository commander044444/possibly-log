"""
Async PostgreSQL layer with connection pool and startup migrations.
All queries are parameterized.
"""
from __future__ import annotations

import logging
from typing import Any, Optional, List, Dict
from contextlib import asynccontextmanager

import asyncpg

import config

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


def _resolve_dsn() -> str:
    dsn = (config.POSTGRESQL_URL or "").strip()
    if not dsn or dsn == "PUT_RAILWAY_POSTGRESQL_URL_HERE":
        raise RuntimeError(
            "POSTGRESQL_URL is not set in config.py. "
            "Paste your Railway PostgreSQL connection string into config.POSTGRESQL_URL."
        )
    if dsn.startswith("postgres://"):
        dsn = dsn.replace("postgres://", "postgresql://", 1)
    return dsn


async def init_db() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    dsn = _resolve_dsn()
    try:
        _pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=config.DB_POOL_MIN,
            max_size=config.DB_POOL_MAX,
            command_timeout=config.DB_COMMAND_TIMEOUT,
        )
    except Exception as e:
        logger.critical("Failed to connect to PostgreSQL: %s", e)
        raise RuntimeError(
            f"Cannot connect to PostgreSQL using config.POSTGRESQL_URL. "
            f"Check host/user/password/database. Underlying error: {e}"
        ) from e
    logger.info("Database pool created (POSTGRESQL_URL)")
    await run_migrations()
    return _pool


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db() first.")
    return _pool


@asynccontextmanager
async def acquire():
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def transaction():
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn


# ─── Schema / Migrations ──────────────────────────────

SCHEMA_SQL = """
-- users
CREATE TABLE IF NOT EXISTS users (
    user_id         BIGINT PRIMARY KEY,
    username        TEXT,
    first_name      TEXT,
    last_name       TEXT,
    display_name    TEXT,
    is_banned       BOOLEAN NOT NULL DEFAULT FALSE,
    ban_reason      TEXT,
    trial_used      BOOLEAN NOT NULL DEFAULT FALSE,
    trial_started_at TIMESTAMPTZ,
    trial_expires_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- dynamic VIP plans (admin-managed)
CREATE TABLE IF NOT EXISTS plans (
    id                  BIGSERIAL PRIMARY KEY,
    name                TEXT NOT NULL,
    slug                TEXT NOT NULL UNIQUE,
    description         TEXT,
    price               INTEGER NOT NULL,
    duration_days       INTEGER NOT NULL,
    max_channels        INTEGER,
    min_interval_minutes INTEGER,
    max_news_per_day    INTEGER,
    max_sources         INTEGER,
    features            TEXT,
    enabled             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- subscriptions
CREATE TABLE IF NOT EXISTS subscriptions (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    plan_id         BIGINT,
    plan_key        TEXT NOT NULL,
    plan_name       TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    payment_method  TEXT,
    payment_id      BIGINT,
    license_id      BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);

-- payment_requests (amount is snapshot at request time)
CREATE TABLE IF NOT EXISTS payment_requests (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    plan_id         BIGINT,
    plan_key        TEXT NOT NULL,
    plan_name       TEXT,
    method          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    amount          INTEGER NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'IRR',
    admin_note      TEXT,
    receipt_file_id TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_payment_requests_user ON payment_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_payment_requests_status ON payment_requests(status);

-- licenses
CREATE TABLE IF NOT EXISTS licenses (
    id              BIGSERIAL PRIMARY KEY,
    code_hash       TEXT NOT NULL UNIQUE,
    code_plain      TEXT,
    user_id         BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    payment_id      BIGINT REFERENCES payment_requests(id),
    plan_id         BIGINT,
    plan_key        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    expires_at      TIMESTAMPTZ NOT NULL,
    used_at         TIMESTAMPTZ,
    used_by         BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_licenses_user ON licenses(user_id);
CREATE INDEX IF NOT EXISTS idx_licenses_status ON licenses(status);

-- per-user daily publish counter (for FREE limits)
CREATE TABLE IF NOT EXISTS user_daily_publish (
    user_id         BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    date            DATE NOT NULL,
    publish_count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, date)
);

-- channels
CREATE TABLE IF NOT EXISTS channels (
    id              BIGSERIAL PRIMARY KEY,
    channel_id      BIGINT NOT NULL UNIQUE,
    channel_username TEXT,
    channel_title   TEXT,
    channel_bio     TEXT,
    owner_user_id   BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'registered',  -- registered | active | stopped | removed
    is_active       BOOLEAN NOT NULL DEFAULT FALSE,
    news_interval   INTEGER NOT NULL DEFAULT 5,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_channels_owner ON channels(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_channels_active ON channels(is_active);

-- channel_categories
CREATE TABLE IF NOT EXISTS channel_categories (
    channel_id      BIGINT NOT NULL REFERENCES channels(channel_id) ON DELETE CASCADE,
    category_key    TEXT NOT NULL,
    PRIMARY KEY (channel_id, category_key)
);

-- channel_settings (moderation etc.)
CREATE TABLE IF NOT EXISTS channel_settings (
    channel_id          BIGINT PRIMARY KEY REFERENCES channels(channel_id) ON DELETE CASCADE,
    anti_profanity      BOOLEAN NOT NULL DEFAULT FALSE,
    anti_link           BOOLEAN NOT NULL DEFAULT FALSE,
    anti_long_message   BOOLEAN NOT NULL DEFAULT FALSE,
    max_message_length  INTEGER NOT NULL DEFAULT 500,
    anti_flood          BOOLEAN NOT NULL DEFAULT FALSE,
    flood_limit         INTEGER NOT NULL DEFAULT 5,
    flood_window        INTEGER NOT NULL DEFAULT 10,
    rules_text          TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- news_sources
CREATE TABLE IF NOT EXISTS news_sources (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    base_url        TEXT,
    feed_url        TEXT,
    source_type     TEXT NOT NULL DEFAULT 'rss',  -- rss | html | api
    category_key    TEXT,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    priority        INTEGER NOT NULL DEFAULT 100,
    timeout         INTEGER NOT NULL DEFAULT 15,
    last_success    TIMESTAMPTZ,
    last_error      TEXT,
    health_status   TEXT NOT NULL DEFAULT 'unknown',  -- healthy | failing | unknown
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- news_items (global dedup)
CREATE TABLE IF NOT EXISTS news_items (
    id              BIGSERIAL PRIMARY KEY,
    source_id       BIGINT REFERENCES news_sources(id),
    source_name     TEXT,
    url             TEXT NOT NULL,
    canonical_url   TEXT NOT NULL,
    url_hash        TEXT NOT NULL,
    external_id     TEXT,
    title           TEXT NOT NULL,
    normalized_title TEXT,
    content_hash    TEXT,
    description     TEXT,
    image_url       TEXT,
    video_url       TEXT,
    category_key    TEXT,
    published_at    TIMESTAMPTZ,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (url_hash)
);
CREATE INDEX IF NOT EXISTS idx_news_items_canonical ON news_items(canonical_url);
CREATE INDEX IF NOT EXISTS idx_news_items_title ON news_items(normalized_title);
CREATE INDEX IF NOT EXISTS idx_news_items_fetched ON news_items(fetched_at);

-- published_news (per-channel publish tracking)
CREATE TABLE IF NOT EXISTS published_news (
    id              BIGSERIAL PRIMARY KEY,
    channel_id      BIGINT NOT NULL REFERENCES channels(channel_id) ON DELETE CASCADE,
    news_id         BIGINT NOT NULL REFERENCES news_items(id) ON DELETE CASCADE,
    published_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (channel_id, news_id)
);

-- channel_daily_stats
CREATE TABLE IF NOT EXISTS channel_daily_stats (
    channel_id      BIGINT NOT NULL REFERENCES channels(channel_id) ON DELETE CASCADE,
    date            DATE NOT NULL,
    messages        INTEGER NOT NULL DEFAULT 0,
    text_count      INTEGER NOT NULL DEFAULT 0,
    photo_count     INTEGER NOT NULL DEFAULT 0,
    video_count     INTEGER NOT NULL DEFAULT 0,
    gif_count       INTEGER NOT NULL DEFAULT 0,
    voice_count     INTEGER NOT NULL DEFAULT 0,
    audio_count     INTEGER NOT NULL DEFAULT 0,
    sticker_count   INTEGER NOT NULL DEFAULT 0,
    file_count      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (channel_id, date)
);

-- banned_words
CREATE TABLE IF NOT EXISTS banned_words (
    id              BIGSERIAL PRIMARY KEY,
    word            TEXT NOT NULL UNIQUE,
    created_by      BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- moderation_logs
CREATE TABLE IF NOT EXISTS moderation_logs (
    id              BIGSERIAL PRIMARY KEY,
    channel_id      BIGINT,
    user_id         BIGINT,
    action          TEXT NOT NULL,
    reason          TEXT,
    message_preview TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- tickets
CREATE TABLE IF NOT EXISTS tickets (
    id              BIGSERIAL PRIMARY KEY,
    ticket_code     TEXT NOT NULL UNIQUE,
    user_id         BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    category        TEXT NOT NULL,
    subject         TEXT,
    message         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',  -- open | answered | closed
    admin_id        BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);

-- ticket_messages
CREATE TABLE IF NOT EXISTS ticket_messages (
    id              BIGSERIAL PRIMARY KEY,
    ticket_id       BIGINT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    sender_type     TEXT NOT NULL,  -- user | admin
    sender_id       BIGINT NOT NULL,
    message         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- user_states (conversation state recovery after restart)
CREATE TABLE IF NOT EXISTS user_states (
    user_id         BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    state           TEXT NOT NULL,
    data            JSONB DEFAULT '{}',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- admin_logs
CREATE TABLE IF NOT EXISTS admin_logs (
    id              BIGSERIAL PRIMARY KEY,
    admin_id        BIGINT NOT NULL,
    action          TEXT NOT NULL,
    target_id       BIGINT,
    details         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- bot admins (editable from /admin; config.ADMIN_ID is always super)
CREATE TABLE IF NOT EXISTS bot_admins (
    user_id         BIGINT PRIMARY KEY,
    username        TEXT,
    role            TEXT NOT NULL DEFAULT 'admin',  -- super | admin
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    is_banned       BOOLEAN NOT NULL DEFAULT FALSE,
    note            TEXT,
    can_users       BOOLEAN NOT NULL DEFAULT TRUE,
    can_payments    BOOLEAN NOT NULL DEFAULT TRUE,
    can_broadcast   BOOLEAN NOT NULL DEFAULT FALSE,
    can_plans       BOOLEAN NOT NULL DEFAULT FALSE,
    can_card        BOOLEAN NOT NULL DEFAULT FALSE,
    can_sources     BOOLEAN NOT NULL DEFAULT FALSE,
    can_tickets     BOOLEAN NOT NULL DEFAULT TRUE,
    can_settings    BOOLEAN NOT NULL DEFAULT FALSE,
    can_manage_admins BOOLEAN NOT NULL DEFAULT FALSE,
    can_stats       BOOLEAN NOT NULL DEFAULT TRUE,
    can_channels    BOOLEAN NOT NULL DEFAULT TRUE,
    can_licenses    BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- system_settings (key-value for admin-editable config)
CREATE TABLE IF NOT EXISTS system_settings (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- broadcasts
CREATE TABLE IF NOT EXISTS broadcasts (
    id              BIGSERIAL PRIMARY KEY,
    admin_id        BIGINT NOT NULL,
    target_type     TEXT NOT NULL,
    message_text    TEXT NOT NULL,
    total_targets   INTEGER DEFAULT 0,
    sent_count      INTEGER DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


async def run_migrations() -> None:
    async with acquire() as conn:
        await conn.execute(SCHEMA_SQL)
        # additive columns for older DBs
        await conn.execute(
            """
            ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS plan_id BIGINT;
            ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS plan_name TEXT;
            ALTER TABLE payment_requests ADD COLUMN IF NOT EXISTS plan_id BIGINT;
            ALTER TABLE payment_requests ADD COLUMN IF NOT EXISTS plan_name TEXT;
            ALTER TABLE payment_requests ADD COLUMN IF NOT EXISTS currency TEXT DEFAULT 'IRR';
            ALTER TABLE licenses ADD COLUMN IF NOT EXISTS plan_id BIGINT;
            ALTER TABLE channels ALTER COLUMN news_interval SET DEFAULT 180;
            ALTER TABLE bot_admins ADD COLUMN IF NOT EXISTS can_users BOOLEAN NOT NULL DEFAULT TRUE;
            ALTER TABLE bot_admins ADD COLUMN IF NOT EXISTS can_payments BOOLEAN NOT NULL DEFAULT TRUE;
            ALTER TABLE bot_admins ADD COLUMN IF NOT EXISTS can_broadcast BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE bot_admins ADD COLUMN IF NOT EXISTS can_plans BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE bot_admins ADD COLUMN IF NOT EXISTS can_card BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE bot_admins ADD COLUMN IF NOT EXISTS can_sources BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE bot_admins ADD COLUMN IF NOT EXISTS can_tickets BOOLEAN NOT NULL DEFAULT TRUE;
            ALTER TABLE bot_admins ADD COLUMN IF NOT EXISTS can_settings BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE bot_admins ADD COLUMN IF NOT EXISTS can_manage_admins BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE bot_admins ADD COLUMN IF NOT EXISTS can_stats BOOLEAN NOT NULL DEFAULT TRUE;
            ALTER TABLE bot_admins ADD COLUMN IF NOT EXISTS can_channels BOOLEAN NOT NULL DEFAULT TRUE;
            ALTER TABLE bot_admins ADD COLUMN IF NOT EXISTS can_licenses BOOLEAN NOT NULL DEFAULT TRUE;

            """
        )
        await conn.execute(
            """
            INSERT INTO system_settings (key, value) VALUES
                ('card_number', $1),
                ('card_holder', $2),
                ('free_max_channels', $3),
                ('free_min_interval', $4),
                ('free_max_news_per_day', $5),
                ('free_max_sources', $6)
            ON CONFLICT (key) DO NOTHING
            """,
            config.CARD_NUMBER,
            config.CARD_HOLDER,
            str(config.FREE_MAX_CHANNELS),
            str(config.FREE_MIN_NEWS_INTERVAL_MINUTES),
            str(config.FREE_MAX_NEWS_PER_DAY),
            str(config.FREE_MAX_SOURCES),
        )
        await conn.execute(
            """
            INSERT INTO bot_admins (user_id, username, role, is_active, is_banned)
            VALUES ($1, $2, 'super', TRUE, FALSE)
            ON CONFLICT (user_id) DO UPDATE SET
                role = 'super',
                is_active = TRUE,
                username = COALESCE(EXCLUDED.username, bot_admins.username)
            """,
            int(config.ADMIN_ID),
            (getattr(config, "ADMIN_USERNAME", None) or "").lstrip("@") or None,
        )
        # seed default VIP plans if empty
        count = await conn.fetchval("SELECT COUNT(*) FROM plans")
        if not count:
            await conn.execute(
                """
                INSERT INTO plans (name, slug, description, price, duration_days,
                    max_channels, min_interval_minutes, max_news_per_day, max_sources, enabled)
                VALUES
                    ('VIP هفت‌روزه', 'vip_7d', 'دسترسی VIP کامل برای ۷ روز', 5000, 7, 10, 3, NULL, NULL, TRUE),
                    ('VIP ماهانه', 'vip_30d', 'دسترسی VIP کامل برای ۳۰ روز', 15000, 30, 20, 3, NULL, NULL, TRUE),
                    ('VIP سه‌ماهه', 'vip_90d', 'دسترسی VIP کامل برای ۹۰ روز', 35000, 90, 50, 3, NULL, NULL, TRUE)
                """
            )
        await conn.execute(
            """
            INSERT INTO news_sources (name, feed_url, source_type, category_key, priority, enabled)
            SELECT * FROM (VALUES
                ('ISNA', 'https://www.isna.ir/rss', 'rss', 'iran', 10, TRUE),
                ('YJC', 'https://www.yjc.ir/fa/rss', 'rss', 'iran', 20, TRUE),
                ('Tasnim', 'https://www.tasnimnews.com/fa/rss', 'rss', 'iran', 30, TRUE)
            ) AS v(name, feed_url, source_type, category_key, priority, enabled)
            WHERE NOT EXISTS (SELECT 1 FROM news_sources LIMIT 1)
            """
        )
        await conn.execute(
            "ALTER TABLE channel_daily_stats ADD COLUMN IF NOT EXISTS members_count INTEGER"
        )
        
        # seed primary admin from config (always present)
        await conn.execute(
            """
            INSERT INTO bot_admins (user_id, username, role, is_active, is_banned)
            VALUES ($1, $2, 'super', TRUE, FALSE)
            ON CONFLICT (user_id) DO UPDATE SET
                role = 'super',
                is_active = TRUE,
                username = COALESCE(EXCLUDED.username, bot_admins.username)
            """,
            int(config.ADMIN_ID),
            (config.ADMIN_USERNAME or "").lstrip("@") or None,
        )

        logger.info("Migrations applied")


# ─── Helper query wrappers ─────────────────────────────

async def fetchrow(query: str, *args) -> Optional[asyncpg.Record]:
    async with acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetch(query: str, *args) -> List[asyncpg.Record]:
    async with acquire() as conn:
        return await conn.fetch(query, *args)


async def execute(query: str, *args) -> str:
    async with acquire() as conn:
        return await conn.execute(query, *args)


async def fetchval(query: str, *args) -> Any:
    async with acquire() as conn:
        return await conn.fetchval(query, *args)
