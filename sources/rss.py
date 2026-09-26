"""RSS/Atom source using feedparser (sync wrapped in executor)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import List, Optional

import aiohttp
import feedparser

from sources.base import BaseSource, NewsItem

logger = logging.getLogger(__name__)


class RSSSource(BaseSource):
    def __init__(
        self,
        name: str,
        feed_url: str,
        category_key: Optional[str] = None,
        timeout: int = 15,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        self.name = name
        self.feed_url = feed_url
        self.category_key = category_key
        self.timeout = timeout
        self._session = session

    async def fetch(self, limit: int = 10) -> List[NewsItem]:
        try:
            text = await self._download()
            if not text:
                return []
            loop = asyncio.get_event_loop()
            feed = await loop.run_in_executor(None, feedparser.parse, text)
            items: List[NewsItem] = []
            for entry in feed.entries[:limit]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title or not link:
                    continue
                desc = (entry.get("summary") or entry.get("description") or "")[:2000]
                image = self._extract_image(entry)
                published = self._parse_date(entry)
                items.append(NewsItem(
                    title=title,
                    url=link,
                    description=desc,
                    image_url=image,
                    published_at=published,
                    category_key=self.category_key,
                    external_id=entry.get("id") or entry.get("guid"),
                    source_name=self.name,
                ))
            return items
        except asyncio.TimeoutError:
            logger.warning("RSS timeout: %s", self.name)
            return []
        except Exception as e:
            logger.warning("RSS error %s: %s", self.name, e)
            return []

    async def _download(self) -> Optional[str]:
        owns = False
        session = self._session
        if session is None:
            session = aiohttp.ClientSession()
            owns = True
        try:
            async with session.get(
                self.feed_url,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={"User-Agent": "BaleNewsBot/1.0"},
            ) as resp:
                if resp.status != 200:
                    return None
                return await resp.text()
        finally:
            if owns:
                await session.close()

    def _extract_image(self, entry) -> Optional[str]:
        if "media_content" in entry:
            for m in entry.media_content:
                if m.get("url"):
                    return m["url"]
        if "media_thumbnail" in entry:
            for m in entry.media_thumbnail:
                if m.get("url"):
                    return m["url"]
        if "enclosures" in entry:
            for e in entry.enclosures:
                if e.get("type", "").startswith("image") and e.get("href"):
                    return e["href"]
        return None

    def _parse_date(self, entry) -> Optional[datetime]:
        for key in ("published", "updated", "created"):
            val = entry.get(key)
            if not val:
                continue
            try:
                return parsedate_to_datetime(val)
            except Exception:
                continue
        return None
