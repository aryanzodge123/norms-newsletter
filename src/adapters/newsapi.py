"""NewsAPI top-headlines adapter (SPEC 6.1). Keyed source.

The key comes from src.config.get_settings().newsapi_key, never from the
environment directly (CLAUDE.md rule: config.py is the only env reader).
A missing key raises a clear RuntimeError at construction so the collector
marks the run partial rather than failing silently. Registered disabled
until the key is set.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

import httpx

from ..config import get_settings
from .base import RawItem, build_item

log = logging.getLogger(__name__)

API_URL = "https://newsapi.org/v2/top-headlines"
TIMEOUT_SECONDS = 15.0


def parse_iso8601(value: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp. Return None rather than guessing."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


class NewsAPIAdapter:
    name = "newsapi"
    source_type = "json"

    def __init__(
        self,
        *,
        topic_hint: str,
        max_items: int,
        run_id: str,
        name: str | None = None,
        feed_url: str | None = None,  # unused; the endpoint is fixed
        shortener_hosts: Iterable[str] = (),
        client: httpx.Client | None = None,
    ) -> None:
        if name:
            self.name = name
        self.topic_hint = topic_hint
        self.max_items = max_items
        self.run_id = run_id
        self.shortener_hosts = tuple(shortener_hosts)
        self._client = client
        self.api_key = get_settings().newsapi_key
        if not self.api_key:
            raise RuntimeError(
                f"{self.name}: NEWSAPI_KEY is not set. Enable this source only "
                "once the key is in .env or Actions secrets."
            )

    def fetch(self, since: datetime) -> list[RawItem]:
        owns_client = self._client is None
        client = self._client or httpx.Client(
            timeout=TIMEOUT_SECONDS, follow_redirects=True
        )
        try:
            response = client.get(
                API_URL,
                params={
                    "language": "en",
                    "pageSize": self.max_items,
                    "apiKey": self.api_key,
                },
            )
            response.raise_for_status()
            return self.parse(response.json(), since)
        finally:
            if owns_client:
                client.close()

    def parse(self, payload: dict, since: datetime) -> list[RawItem]:
        """Normalize a decoded payload. Split out so tests run offline."""
        articles = payload.get("articles") or []
        items: list[RawItem] = []
        for entry in articles:
            if len(items) >= self.max_items:
                break
            item = self._normalize(entry)
            if item is None or item.published_at < since:
                continue
            items.append(item)
        return items

    def _normalize(self, entry: dict) -> RawItem | None:
        """A malformed entry is skipped, never fatal."""
        title = entry.get("title")
        link = entry.get("url")
        published_at = parse_iso8601(entry.get("publishedAt"))
        if not title or not link or published_at is None:
            log.warning("%s: skipping entry missing title, url, or date", self.name)
            return None

        try:
            return build_item(
                source=self.name,
                source_type=self.source_type,
                topic_hint=self.topic_hint,
                url=link,
                title=title,
                body=entry.get("description") or entry.get("content"),
                author=entry.get("author"),
                published_at=published_at,
                run_id=self.run_id,
                shortener_hosts=self.shortener_hosts,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: entry failed to normalize: %s", self.name, exc)
            return None
