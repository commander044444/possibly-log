"""Shared helpers: hashing, canonical URL, license generation, text utils."""
from __future__ import annotations

import hashlib
import re
import secrets
import string
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import config


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_license(code: str) -> str:
    return hashlib.sha256(code.strip().lower().encode("utf-8")).hexdigest()


def generate_license_code(length: int = None) -> str:
    length = length or config.LICENSE_LENGTH
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_ticket_code() -> str:
    return f"TICKET-{secrets.randbelow(90000) + 10000}"


TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid", "_ga", "ref", "source",
}


def canonicalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        # drop fragment
        query = parse_qs(parsed.query, keep_blank_values=False)
        cleaned = {k: v for k, v in query.items() if k.lower() not in TRACKING_PARAMS}
        new_query = urlencode(cleaned, doseq=True)
        path = parsed.path.rstrip("/") or "/"
        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            new_query,
            "",
        ))
    except Exception:
        return url.strip()


def normalize_title(title: str) -> str:
    if not title:
        return ""
    t = title.strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^\w\s\u0600-\u06FF]", "", t)
    return t[:300]


def content_hash(title: str, description: str = "") -> str:
    base = f"{normalize_title(title)}|{(description or '')[:500]}"
    return hash_text(base)


def truncate_text(text: str, max_len: int = 3500, suffix: str = "…") -> str:
    """Truncate without breaking mid-word if possible."""
    if not text or len(text) <= max_len:
        return text or ""
    cut = text[: max_len - len(suffix)]
    # try not to cut mid-word
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + suffix


def format_remaining(expires_at: datetime) -> str:
    now = utcnow()
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    delta = expires_at - now
    if delta.total_seconds() <= 0:
        return "منقضی شده"
    days = delta.days
    hours = delta.seconds // 3600
    mins = (delta.seconds % 3600) // 60
    parts = []
    if days:
        parts.append(f"{days} روز")
    if hours:
        parts.append(f"{hours} ساعت")
    if mins and not days:
        parts.append(f"{mins} دقیقه")
    return " و ".join(parts) if parts else "کمتر از یک دقیقه"


def is_super_admin(user_id: int) -> bool:
    """Owner from config.py — cannot be removed."""
    return int(user_id) == int(config.ADMIN_ID)


async def is_admin(user_id: int) -> bool:
    """True if config owner OR active row in bot_admins."""
    uid = int(user_id)
    if uid == int(config.ADMIN_ID):
        return True
    try:
        import database as db
        row = await db.fetchrow(
            """
            SELECT 1 FROM bot_admins
            WHERE user_id = $1 AND is_active = TRUE AND COALESCE(is_banned, FALSE) = FALSE
            """,
            uid,
        )
        return row is not None
    except Exception:
        return False


def format_user_ref(username: str | None = None, user_id: int | None = None) -> str:
    """
    Prefer clickable @username for admin messages.
    Never show bare numeric id when username is available.
    """
    if username:
        u = str(username).strip().lstrip("@")
        if u:
            return f"@{u}"
    if user_id is not None:
        return f"کاربر (بدون یوزرنیم)"
    return "کاربر"


async def resolve_user_ref(user_id: int) -> str:
    """Lookup username from DB; return @username when possible."""
    try:
        import database as db
        row = await db.fetchrow(
            "SELECT username FROM users WHERE user_id = $1",
            int(user_id),
        )
        if row and row.get("username"):
            return format_user_ref(row["username"], user_id)
    except Exception:
        pass
    return format_user_ref(None, user_id)


# Permission keys used across admin panel
ADMIN_PERMS = (
    "can_users",
    "can_payments",
    "can_broadcast",
    "can_plans",
    "can_card",
    "can_sources",
    "can_tickets",
    "can_settings",
    "can_manage_admins",
    "can_stats",
    "can_channels",
    "can_licenses",
)

PERM_LABELS = {
    "can_users": "کاربران",
    "can_payments": "پرداخت‌ها / رسید",
    "can_broadcast": "همگانی (Broadcast)",
    "can_plans": "پلن و قیمت",
    "can_card": "شماره کارت",
    "can_sources": "منابع خبری",
    "can_tickets": "تیکت‌ها",
    "can_settings": "تنظیمات",
    "can_manage_admins": "مدیریت ادمین‌ها",
    "can_stats": "آمار سیستم",
    "can_channels": "کانال‌ها",
    "can_licenses": "لایسنس‌ها",
}


async def get_admin_record(user_id: int) -> dict | None:
    uid = int(user_id)
    if uid == int(config.ADMIN_ID):
        # virtual super record
        rec = {k: True for k in ADMIN_PERMS}
        rec.update({
            "user_id": uid,
            "username": getattr(config, "ADMIN_USERNAME", None),
            "role": "super",
            "is_active": True,
            "is_banned": False,
        })
        return rec
    try:
        import database as db
        row = await db.fetchrow("SELECT * FROM bot_admins WHERE user_id = $1", uid)
        return dict(row) if row else None
    except Exception:
        return None


async def has_admin_perm(user_id: int, perm: str) -> bool:
    """Super owner always True. Others need active + perm flag."""
    uid = int(user_id)
    if uid == int(config.ADMIN_ID):
        return True
    rec = await get_admin_record(uid)
    if not rec:
        return False
    if not rec.get("is_active", True) or rec.get("is_banned"):
        return False
    if rec.get("role") == "super":
        return True
    return bool(rec.get(perm, False))


async def list_admin_ids_with_perm(perm: str) -> list[int]:
    """Notify targets: owner + admins that have perm."""
    ids = [int(config.ADMIN_ID)]
    try:
        import database as db
        rows = await db.fetch(
            f"""
            SELECT user_id FROM bot_admins
            WHERE is_active = TRUE AND COALESCE(is_banned, FALSE) = FALSE
              AND (role = 'super' OR {perm} = TRUE)
            """
        )
        for r in rows:
            uid = int(r["user_id"])
            if uid not in ids:
                ids.append(uid)
    except Exception:
        pass
    return ids
