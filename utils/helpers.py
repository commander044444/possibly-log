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


def is_admin(user_id: int) -> bool:
    return int(user_id) == int(config.ADMIN_ID)
