"""Ars Technica RSS adapter (SPEC 6.1).

The generic RSS shape lives here for M1. When the rest of the v1 feed list
lands in M6 this becomes a shared RSS base class with per-feed subclasses.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Iterable

import feedparser
import httpx

from .base import RawItem, build_item
from .hackernews import strip_html

log = logging.getLogger(__name__)

FEED_URL = "https://feeds.arstechnica.com/arstechnica/index"
TIMEOUT_SECONDS = 10.0


def parse_published(entry) -> datetime | None:
    """RSS dates are unreliable. Return None rather than guessing."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None


class ArsTechnicaAdapter:
    name = "arstechnica"
    source_type = "rss"
    feed_url = FEED_URL

    def __init__(
        self,
        *,
        topic_hint: str,
        max_items: int,
        run_id: str,
        name: str | None = None,
        feed_url: str | None = None,
        shortener_hosts: Iterable[str] = (),
        client: httpx.Client | None = None,
    ) -> None:
        if name:
            self.name = name
        if feed_url:
            self.feed_url = feed_url
        self.topic_hint = topic_hint
        self.max_items = max_items
        self.run_id = run_id
        self.shortener_hosts = tuple(shortener_hosts)
        self._client = client

    def fetch(self, since: datetime) -> list[RawItem]:
        owns_client = self._client is None
        client = self._client or httpx.Client(
            timeout=TIMEOUT_SECONDS, follow_redirects=True
        )
        try:
            response = client.get(self.feed_url)
            response.raise_for_status()
            return self.parse(response.text, since)
        finally:
            if owns_client:
                client.close()

    def parse(self, feed_text: str, since: datetime) -> list[RawItem]:
        """Normalize a feed body. Split out so tests run without network."""
        feed = feedparser.parse(feed_text)
        items: list[RawItem] = []
        for entry in feed.entries:
            if len(items) >= self.max_items:
                break
            item = self._normalize(entry)
            if item is None or item.published_at < since:
                continue
            items.append(item)
        return items

    def _normalize(self, entry) -> RawItem | None:
        """A malformed entry is skipped, never fatal to the feed."""
        title = entry.get("title")
        link = entry.get("link")
        published_at = parse_published(entry)
        if not title or not link or published_at is None:
            log.warning("%s: skipping entry missing title, link, or date", self.name)
            return None

        try:
            return build_item(
                source=self.name,
                source_type=self.source_type,
                topic_hint=self.topic_hint,
                url=link,
                title=title,
                body=strip_html(entry.get("summary")),
                author=entry.get("author"),
                published_at=published_at,
                run_id=self.run_id,
                shortener_hosts=self.shortener_hosts,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: entry failed to normalize: %s", self.name, exc)
            return None
