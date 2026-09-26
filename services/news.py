"""
News fetch, multi-layer dedup, and publish pipeline.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Dict, Any

import aiohttp

import database as db
from sources.base import NewsItem
from sources.rss import RSSSource
from utils.helpers import canonicalize_url, normalize_title, content_hash, hash_text, truncate_text
import config

logger = logging.getLogger(__name__)

_http_session: Optional[aiohttp.ClientSession] = None


async def get_http_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=config.SOURCE_TIMEOUT),
            headers={"User-Agent": "BaleNewsBot/1.0"},
        )
    return _http_session


async def close_http_session() -> None:
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()
        _http_session = None


async def load_enabled_sources() -> List[Dict[str, Any]]:
    rows = await db.fetch(
        """
        SELECT * FROM news_sources
        WHERE enabled = TRUE
        ORDER BY priority ASC, id ASC
        """
    )
    return [dict(r) for r in rows]


async def mark_source_health(source_id: int, ok: bool, error: Optional[str] = None) -> None:
    if ok:
        await db.execute(
            """
            UPDATE news_sources SET
                last_success = NOW(),
                last_error = NULL,
                health_status = 'healthy'
            WHERE id = $1
            """,
            source_id,
        )
    else:
        await db.execute(
            """
            UPDATE news_sources SET
                last_error = $2,
                health_status = 'failing'
            WHERE id = $1
            """,
            source_id, (error or "")[:500],
        )


async def store_news_item(item: NewsItem, source_id: Optional[int] = None) -> Optional[int]:
    """
    Insert news with multi-layer dedup.
    Returns news_id if newly inserted, else None.
    """
    if not item.title or not item.url:
        return None
    canonical = canonicalize_url(item.url)
    url_h = hash_text(canonical)
    norm_title = normalize_title(item.title)
    c_hash = content_hash(item.title, item.description or "")

    # check existing by url_hash
    existing = await db.fetchval(
        "SELECT id FROM news_items WHERE url_hash = $1", url_h
    )
    if existing:
        return None

    # soft check normalized title (same day-ish)
    existing_title = await db.fetchval(
        """
        SELECT id FROM news_items
        WHERE normalized_title = $1 AND fetched_at > NOW() - INTERVAL '48 hours'
        LIMIT 1
        """,
        norm_title,
    )
    if existing_title:
        return None

    try:
        row = await db.fetchrow(
            """
            INSERT INTO news_items (
                source_id, source_name, url, canonical_url, url_hash,
                external_id, title, normalized_title, content_hash,
                description, image_url, video_url, category_key, published_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            ON CONFLICT (url_hash) DO NOTHING
            RETURNING id
            """,
            source_id,
            item.source_name,
            item.url,
            canonical,
            url_h,
            item.external_id,
            item.title[:500],
            norm_title,
            c_hash,
            (item.description or "")[:4000],
            item.image_url,
            item.video_url,
            item.category_key,
            item.published_at,
        )
        return row["id"] if row else None
    except Exception as e:
        logger.warning("store_news_item: %s", e)
        return None


async def fetch_from_sources(limit_per: int = None) -> int:
    """Fetch from all enabled sources with failover. Returns new items count."""
    limit_per = limit_per or config.NEWS_FETCH_LIMIT_PER_SOURCE
    sources = await load_enabled_sources()
    session = await get_http_session()
    new_count = 0
    for src in sources:
        try:
            if src["source_type"] != "rss" or not src.get("feed_url"):
                continue
            rss = RSSSource(
                name=src["name"],
                feed_url=src["feed_url"],
                category_key=src.get("category_key"),
                timeout=src.get("timeout") or config.SOURCE_TIMEOUT,
                session=session,
            )
            items = await rss.fetch(limit=limit_per)
            if not items:
                await mark_source_health(src["id"], False, "no items / fetch failed")
                continue
            for it in items:
                nid = await store_news_item(it, source_id=src["id"])
                if nid:
                    new_count += 1
            await mark_source_health(src["id"], True)
        except Exception as e:
            logger.exception("source %s failed", src.get("name"))
            await mark_source_health(src["id"], False, str(e))
            continue  # failover to next
    return new_count


async def get_unpublished_for_channel(
    channel_id: int,
    categories: List[str],
    limit: int = 1,
) -> List[dict]:
    if not categories:
        return []
    rows = await db.fetch(
        """
        SELECT n.* FROM news_items n
        WHERE n.category_key = ANY($1::text[])
          AND NOT EXISTS (
              SELECT 1 FROM published_news p
              WHERE p.channel_id = $2 AND p.news_id = n.id
          )
        ORDER BY n.fetched_at DESC
        LIMIT $3
        """,
        categories, channel_id, limit,
    )
    return [dict(r) for r in rows]


async def mark_published(channel_id: int, news_id: int) -> bool:
    try:
        await db.execute(
            """
            INSERT INTO published_news (channel_id, news_id)
            VALUES ($1, $2)
            ON CONFLICT (channel_id, news_id) DO NOTHING
            """,
            channel_id, news_id,
        )
        return True
    except Exception:
        return False


def format_news_message(news: dict) -> str:
    title = news.get("title") or ""
    desc = news.get("description") or ""
    url = news.get("url") or news.get("canonical_url") or ""
    source = news.get("source_name") or "منبع"
    body = f"📰 {title}\n\n"
    if desc:
        body += truncate_text(desc, 2800) + "\n\n"
    body += f"🔗 {url}\n"
    body += f"📡 منبع: {source}"
    return truncate_text(body, 3900)


async def bump_channel_stats(channel_id: int, kind: str = "text") -> None:
    col_map = {
        "text": "text_count",
        "photo": "photo_count",
        "video": "video_count",
        "gif": "gif_count",
        "voice": "voice_count",
        "audio": "audio_count",
        "sticker": "sticker_count",
        "file": "file_count",
    }
    col = col_map.get(kind, "text_count")
    await db.execute(
        f"""
        INSERT INTO channel_daily_stats (channel_id, date, messages, {col})
        VALUES ($1, CURRENT_DATE, 1, 1)
        ON CONFLICT (channel_id, date) DO UPDATE SET
            messages = channel_daily_stats.messages + 1,
            {col} = channel_daily_stats.{col} + 1
        """,
        channel_id,
    )
