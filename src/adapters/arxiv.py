"""arXiv Atom API adapter (SPEC 6.1). Free, no key needed.

The query endpoint returns an Atom feed, so feedparser handles the body
just like an RSS source. The endpoint itself is fixed here rather than in
the registry: it carries a hardcoded category filter and sort order that
belong to this adapter, not to a generic feed slot. source_type is "api"
because it is a query endpoint, not a published feed.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from typing import Iterable

import feedparser
import httpx

from .arstechnica import parse_published
from .base import RawItem, build_item, user_agent
from .hackernews import strip_html

log = logging.getLogger(__name__)

API_ROOT = "http://export.arxiv.org/api/query"
SEARCH_QUERY = "cat:cs.AI OR cat:cs.LG"
# arXiv's query API is slow and rate-limits hard: measured on prod, 8 of 10
# collector failures were ReadTimeouts, plus one 429 and one 406. So the
# timeout is generous and transient failures are retried (SPEC 6.1).
TIMEOUT_SECONDS = 20.0
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2.0
# The 406 was a content-negotiation miss: arXiv wants an explicit Atom Accept
# header, which httpx's default `*/*` does not always satisfy.
ACCEPT_HEADER = "application/atom+xml"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


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
            response = self._get_with_retry(client)
            return self.parse(response.text, since)
        finally:
            if owns_client:
                client.close()

    def _get_with_retry(self, client: httpx.Client) -> httpx.Response:
        """One GET, retried on transient failure (SPEC 6.1).

        Retries timeouts, transport errors, 429, and 5xx a bounded number of
        times with backoff and jitter. A non-transient status (a 404, say)
        raises at once. After the last attempt the final error propagates, so
        run_adapter records it and the cycle is partial exactly as before.
        """
        params = {
            "search_query": SEARCH_QUERY,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": self.max_items,
        }
        headers = {"Accept": ACCEPT_HEADER, "User-Agent": user_agent()}
        last_exc: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = client.get(API_ROOT, params=params, headers=headers)
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in RETRYABLE_STATUS:
                    raise
                last_exc = exc
            if attempt < MAX_ATTEMPTS:
                delay = BACKOFF_BASE_SECONDS * attempt + random.uniform(0, 0.5)
                log.warning(
                    "%s: transient fetch failure (attempt %d of %d), retrying in %.1fs: %s",
                    self.name, attempt, MAX_ATTEMPTS, delay, last_exc,
                )
                time.sleep(delay)
        assert last_exc is not None
        raise last_exc

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
