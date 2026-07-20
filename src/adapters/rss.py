"""Generic config-driven RSS adapter (SPEC 6.1).

One class serves every plain-RSS source in the registry. The feed location
lives in config/sources.yaml as feed_url rather than in the code, so adding
a feed is a registry edit, not a new module. Bespoke feeds that need custom
parsing (arXiv, CISA quirks) get their own file instead.

Mirrors the ArsTechnica shape: fetch() does the IO, parse(feed_text, since)
is split out so tests run without network, and a malformed entry is skipped
rather than fatal.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

import feedparser
import httpx

from .arstechnica import parse_published
from .base import USER_AGENT, RawItem, build_item
from .hackernews import strip_html

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0


class RSSAdapter:
    source_type = "rss"

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
        if not feed_url:
            raise ValueError(
                "RSSAdapter requires feed_url in the registry entry "
                f"(source {name!r})"
            )
        self.name = name or "rss"
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
            # Identify the caller. Several publishers reject the default
            # client string outright (CNBC returns 403).
            response = client.get(self.feed_url, headers={"User-Agent": USER_AGENT})
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
