"""arXiv Atom API adapter (SPEC 6.1). Free, no key needed.

The query endpoint returns an Atom feed, so feedparser handles the body
just like an RSS source. The endpoint itself is fixed here rather than in
the registry: it carries a hardcoded category filter and sort order that
belong to this adapter, not to a generic feed slot. source_type is "api"
because it is a query endpoint, not a published feed.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

import feedparser
import httpx

from .arstechnica import parse_published
from .base import RawItem, build_item
from .hackernews import strip_html

log = logging.getLogger(__name__)

API_ROOT = "http://export.arxiv.org/api/query"
SEARCH_QUERY = "cat:cs.AI OR cat:cs.LG"
TIMEOUT_SECONDS = 15.0


class ArxivAdapter:
    name = "arxiv"
    source_type = "api"

    def __init__(
        self,
        *,
        topic_hint: str,
        max_items: int,
        run_id: str,
        name: str | None = None,
        feed_url: str | None = None,  # unused; the query endpoint is fixed
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

    def fetch(self, since: datetime) -> list[RawItem]:
        owns_client = self._client is None
        client = self._client or httpx.Client(
            timeout=TIMEOUT_SECONDS, follow_redirects=True
        )
        try:
            response = client.get(
                API_ROOT,
                params={
                    "search_query": SEARCH_QUERY,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                    "max_results": self.max_items,
                },
            )
            response.raise_for_status()
            return self.parse(response.text, since)
        finally:
            if owns_client:
                client.close()

    def parse(self, feed_text: str, since: datetime) -> list[RawItem]:
        """Normalize an Atom body. Split out so tests run without network."""
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

        author = entry.get("author")
        try:
            return build_item(
                source=self.name,
                source_type=self.source_type,
                topic_hint=self.topic_hint,
                url=link,
                title=title,
                body=strip_html(entry.get("summary")),
                author=author,
                published_at=published_at,
                run_id=self.run_id,
                shortener_hosts=self.shortener_hosts,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: entry failed to normalize: %s", self.name, exc)
            return None
