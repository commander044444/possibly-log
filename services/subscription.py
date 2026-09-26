"""
Access tiers: FREE | VIP | BANNED

No Trial. Feature limits drive what FREE vs VIP can do.
News Automation is available on FREE with limits.
"""
from __future__ import annotations

import logging
from datetime import timedelta, date
from typing import Optional, Tuple, Literal, Any, Dict

import database as db
from utils.helpers import utcnow, format_remaining
import config

logger = logging.getLogger(__name__)

AccessTier = Literal["FREE", "VIP", "BANNED"]


async def ensure_user(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> None:
    display = " ".join(filter(None, [first_name, last_name])) or username or str(user_id)
    await db.execute(
        """
        INSERT INTO users (user_id, username, first_name, last_name, display_name, last_seen)
        VALUES ($1, $2, $3, $4, $5, NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            username = COALESCE(EXCLUDED.username, users.username),
            first_name = COALESCE(EXCLUDED.first_name, users.first_name),
            last_name = COALESCE(EXCLUDED.last_name, users.last_name),
            display_name = COALESCE(EXCLUDED.display_name, users.display_name),
            last_seen = NOW()
        """,
        user_id, username, first_name, last_name, display,
    )


async def is_banned(user_id: int) -> bool:
    row = await db.fetchrow("SELECT is_banned FROM users WHERE user_id = $1", user_id)
    return bool(row and row["is_banned"])


async def get_active_subscription(user_id: int) -> Optional[dict]:
    row = await db.fetchrow(
        """
        SELECT s.*, p.name AS live_plan_name, p.max_channels AS p_max_channels,
               p.min_interval_minutes AS p_min_interval,
               p.max_news_per_day AS p_max_news, p.max_sources AS p_max_sources
        FROM subscriptions s
        LEFT JOIN plans p ON p.id = s.plan_id
        WHERE s.user_id = $1 AND s.status = 'active' AND s.expires_at > NOW()
        ORDER BY s.expires_at DESC
        LIMIT 1
        """,
        user_id,
    )
    return dict(row) if row else None


async def get_access_tier(user_id: int) -> AccessTier:
    if await is_banned(user_id):
        return "BANNED"
    if await get_active_subscription(user_id):
        return "VIP"
    return "FREE"


async def has_vip_access(user_id: int) -> bool:
    return await get_access_tier(user_id) == "VIP"


async def require_vip_access(user_id: int) -> Tuple[bool, str]:
    """Only for features that are strictly VIP (short intervals, extra channels, etc.)."""
    tier = await get_access_tier(user_id)
    if tier == "BANNED":
        return False, "🚫 حساب شما توسط مدیریت مسدود شده است."
    if tier == "VIP":
        return True, ""
    return False, config.VIP_UPGRADE_TEXT


async def get_user_limits(user_id: int) -> Dict[str, Any]:
    """
    Effective feature limits for this user.
    VIP uses plan caps (NULL = unlimited). FREE uses config/system_settings.
    """
    tier = await get_access_tier(user_id)
    if tier == "BANNED":
        return {
            "tier": "BANNED",
            "max_channels": 0,
            "min_interval_minutes": 999999,
            "max_news_per_day": 0,
            "max_sources": 0,
            "intervals": [],
        }

    if tier == "VIP":
        sub = await get_active_subscription(user_id)
        max_ch = (sub or {}).get("p_max_channels")
        if max_ch is None:
            max_ch = config.VIP_DEFAULT_MAX_CHANNELS
        min_iv = (sub or {}).get("p_min_interval")
        if min_iv is None:
            min_iv = config.VIP_DEFAULT_MIN_INTERVAL
        max_day = (sub or {}).get("p_max_news")  # None = unlimited
        max_src = (sub or {}).get("p_max_sources")
        return {
            "tier": "VIP",
            "max_channels": int(max_ch),
            "min_interval_minutes": int(min_iv),
            "max_news_per_day": int(max_day) if max_day is not None else None,
            "max_sources": int(max_src) if max_src is not None else None,
            "intervals": [i for i in config.VIP_INTERVALS if i >= int(min_iv)],
        }

    # FREE — prefer system_settings if present
    async def _setting(key: str, default: int) -> int:
        val = await db.fetchval("SELECT value FROM system_settings WHERE key = $1", key)
        try:
            return int(val) if val is not None else default
        except (TypeError, ValueError):
            return default

    max_ch = await _setting("free_max_channels", config.FREE_MAX_CHANNELS)
    min_iv = await _setting("free_min_interval", config.FREE_MIN_NEWS_INTERVAL_MINUTES)
    max_day = await _setting("free_max_news_per_day", config.FREE_MAX_NEWS_PER_DAY)
    max_src = await _setting("free_max_sources", config.FREE_MAX_SOURCES)
    intervals = [i for i in config.FREE_INTERVALS if i >= min_iv]
    if not intervals:
        intervals = [min_iv]
    return {
        "tier": "FREE",
        "max_channels": max_ch,
        "min_interval_minutes": min_iv,
        "max_news_per_day": max_day,
        "max_sources": max_src,
        "intervals": intervals,
    }


async def count_user_channels(user_id: int) -> int:
    return await db.fetchval(
        "SELECT COUNT(*) FROM channels WHERE owner_user_id = $1 AND status != 'removed'",
        user_id,
    ) or 0


async def can_add_channel(user_id: int) -> Tuple[bool, str]:
    limits = await get_user_limits(user_id)
    if limits["tier"] == "BANNED":
        return False, "🚫 حساب شما مسدود است."
    current = await count_user_channels(user_id)
    max_ch = limits["max_channels"]
    if current >= max_ch:
        return False, (
            f"⚠️ در پلن {limits['tier']} حداکثر {max_ch} کانال دارید.\n\n"
            "برای اضافه کردن کانال بیشتر، VIP تهیه کنید."
        )
    return True, ""


async def get_today_publish_count(user_id: int) -> int:
    return await db.fetchval(
        """
        SELECT publish_count FROM user_daily_publish
        WHERE user_id = $1 AND date = CURRENT_DATE
        """,
        user_id,
    ) or 0


async def increment_daily_publish(user_id: int) -> int:
    row = await db.fetchrow(
        """
        INSERT INTO user_daily_publish (user_id, date, publish_count)
        VALUES ($1, CURRENT_DATE, 1)
        ON CONFLICT (user_id, date) DO UPDATE SET
            publish_count = user_daily_publish.publish_count + 1
        RETURNING publish_count
        """,
        user_id,
    )
    return row["publish_count"] if row else 1


async def can_publish_today(user_id: int) -> Tuple[bool, str]:
    limits = await get_user_limits(user_id)
    max_day = limits.get("max_news_per_day")
    if max_day is None:
        return True, ""
    used = await get_today_publish_count(user_id)
    if used >= max_day:
        return False, (
            "⏸ محدودیت روزانه پلن FREE شما به پایان رسیده است.\n\n"
            f"حداکثر خبر امروز: {max_day}\n\n"
            "برای ادامه فعالیت یا افزایش سرعت انتشار، VIP تهیه کنید.\n"
            "فردا دوباره مجاز خواهید بود."
        )
    return True, ""


async def validate_interval(user_id: int, minutes: int) -> Tuple[bool, str]:
    limits = await get_user_limits(user_id)
    allowed = limits.get("intervals") or []
    min_iv = limits["min_interval_minutes"]
    if minutes < min_iv or (allowed and minutes not in allowed):
        if limits["tier"] == "FREE":
            return False, (
                "⚠️ این قابلیت در پلن FREE محدود است.\n\n"
                f"حداقل فاصله انتشار: {min_iv} دقیقه "
                f"({min_iv // 60} ساعت)\n\n"
                "برای intervalهای کوتاه‌تر و فعالیت 24/7، VIP تهیه کنید."
            )
        return False, f"حداقل فاصله مجاز: {min_iv} دقیقه."
    return True, ""


async def list_enabled_plans() -> list:
    rows = await db.fetch(
        """
        SELECT * FROM plans WHERE enabled = TRUE
        ORDER BY price ASC, id ASC
        """
    )
    return [dict(r) for r in rows]


async def get_plan_by_id(plan_id: int) -> Optional[dict]:
    row = await db.fetchrow("SELECT * FROM plans WHERE id = $1", plan_id)
    return dict(row) if row else None


async def get_plan_by_slug(slug: str) -> Optional[dict]:
    row = await db.fetchrow("SELECT * FROM plans WHERE slug = $1", slug)
    return dict(row) if row else None


async def activate_subscription_from_plan(
    user_id: int,
    plan: dict,
    payment_id: Optional[int] = None,
    license_id: Optional[int] = None,
    payment_method: Optional[str] = None,
) -> bool:
    now = utcnow()
    expires = now + timedelta(days=int(plan["duration_days"]))
    async with db.transaction() as conn:
        await conn.execute(
            "UPDATE subscriptions SET status = 'expired' WHERE user_id = $1 AND status = 'active'",
            user_id,
        )
        await conn.execute(
            """
            INSERT INTO subscriptions
                (user_id, plan_id, plan_key, plan_name, started_at, expires_at,
                 status, payment_method, payment_id, license_id)
            VALUES ($1, $2, $3, $4, $5, $6, 'active', $7, $8, $9)
            """,
            user_id,
            plan.get("id"),
            plan.get("slug") or str(plan.get("id")),
            plan.get("name"),
            now,
            expires,
            payment_method,
            payment_id,
            license_id,
        )
    logger.info("VIP activated user=%s plan=%s", user_id, plan.get("slug"))
    return True


async def get_status_text(user_id: int) -> str:
    tier = await get_access_tier(user_id)
    limits = await get_user_limits(user_id)
    if tier == "BANNED":
        return "🚫 حساب مسدود است."

    if tier == "VIP":
        sub = await get_active_subscription(user_id)
        name = (sub or {}).get("plan_name") or (sub or {}).get("live_plan_name") or "VIP"
        rem = format_remaining(sub["expires_at"]) if sub else "—"
        day_cap = limits["max_news_per_day"]
        day_txt = "نامحدود" if day_cap is None else str(day_cap)
        return (
            "👑 اشتراک VIP فعال\n\n"
            f"پلن:\n{name}\n\n"
            f"تاریخ پایان:\n{sub['expires_at'] if sub else '—'}\n\n"
            f"باقی‌مانده:\n{rem}\n\n"
            f"حداکثر کانال: {limits['max_channels']}\n"
            f"حداقل فاصله: {limits['min_interval_minutes']} دقیقه\n"
            f"حداکثر خبر روزانه: {day_txt}\n\n"
            "وضعیت:\n🟢 فعال"
        )

    used_today = await get_today_publish_count(user_id)
    return (
        "🆓 حساب FREE\n\n"
        "اشتراک VIP فعال ندارید — اما News Automation با محدودیت فعال است.\n\n"
        f"حداکثر کانال: {limits['max_channels']}\n"
        f"حداقل فاصله انتشار: {limits['min_interval_minutes']} دقیقه "
        f"({limits['min_interval_minutes'] // 60} ساعت)\n"
        f"حداکثر خبر روزانه: {limits['max_news_per_day']}\n"
        f"منتشرشده امروز: {used_today}\n\n"
        "برای interval کوتاه و فعالیت 24/7، VIP تهیه کنید."
    )


async def set_banned(user_id: int, banned: bool) -> None:
    try:
        await db.execute(
            "UPDATE users SET is_banned = $2, updated_at = NOW() WHERE user_id = $1",
            int(user_id), bool(banned),
        )
    except Exception:
        await db.execute(
            "UPDATE users SET is_banned = $2 WHERE user_id = $1",
            int(user_id), bool(banned),
        )


async def deactivate_subscription(user_id: int) -> bool:
    """Expire active VIP immediately."""
    result = await db.execute(
        """
        UPDATE subscriptions
        SET status = 'expired', expires_at = NOW()
        WHERE user_id = $1 AND status = 'active' AND expires_at > NOW()
        """,
        int(user_id),
    )
    return True


async def gift_plan_to_user(user_id: int, plan_id: int) -> Tuple[bool, str]:
    plan = await get_plan_by_id(plan_id)
    if not plan:
        return False, "پلن یافت نشد."
    ok = await activate_subscription_from_plan(
        user_id, plan, payment_method="admin_gift"
    )
    if ok:
        return True, f"VIP «{plan['name']}» برای کاربر فعال شد."
    return False, "فعال‌سازی ناموفق."
