"""Base news source interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class NewsItem:
    title: str
    url: str
    description: str = ""
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    published_at: Optional[datetime] = None
    category_key: Optional[str] = None
    external_id: Optional[str] = None
    source_name: str = ""


class BaseSource(ABC):
    name: str = "base"
    timeout: int = 15

    @abstractmethod
    async def fetch(self, limit: int = 10) -> List[NewsItem]:
        """Fetch latest items. Must not raise on soft failures; return []."""
        ...
