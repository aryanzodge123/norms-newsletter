"""Hacker News adapter (SPEC 6.1). Free Firebase API, no key needed."""

from __future__ import annotations

import html
import logging
import re
from datetime import UTC, datetime
from typing import Iterable

import httpx

from .base import RawItem, build_item

log = logging.getLogger(__name__)

API_ROOT = "https://hacker-news.firebaseio.com/v0"
TOP_STORIES = f"{API_ROOT}/topstories.json"
TIMEOUT_SECONDS = 10.0

# HN item text is HTML fragments: <p>, <a>, <i>, entities.
TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    return html.unescape(TAG_RE.sub(" ", text))


class HackerNewsAdapter:
    name = "hackernews"
    source_type = "api"

    def __init__(
        self,
        *,
        topic_hint: str,
        max_items: int,
        run_id: str,
        shortener_hosts: Iterable[str] = (),
        client: httpx.Client | None = None,
    ) -> None:
        self.topic_hint = topic_hint
        self.max_items = max_items
        self.run_id = run_id
        self.shortener_hosts = tuple(shortener_hosts)
        self._client = client

    def fetch(self, since: datetime) -> list[RawItem]:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=TIMEOUT_SECONDS)
        try:
            ids = client.get(TOP_STORIES).raise_for_status().json()
            items: list[RawItem] = []
            # Walk the ranked list until the cap is met. Stories older than
            # `since` are skipped rather than ending the walk: the list is
            # ranked by score, not strictly by time.
            for story_id in ids:
                if len(items) >= self.max_items:
                    break
                item = self._fetch_item(client, story_id)
                if item is None:
                    continue
                if item.published_at < since:
                    continue
                items.append(item)
            return items
        finally:
            if owns_client:
                client.close()

    def _fetch_item(self, client: httpx.Client, story_id: int) -> RawItem | None:
        """Normalize one HN item. A bad item is skipped, never fatal."""
        try:
            raw = client.get(f"{API_ROOT}/item/{story_id}.json").raise_for_status().json()
        except Exception as exc:  # noqa: BLE001
            log.warning("hackernews: item %s failed to fetch: %s", story_id, exc)
            return None

        if not raw or raw.get("type") != "story" or raw.get("dead") or raw.get("deleted"):
            return None
        title = raw.get("title")
        timestamp = raw.get("time")
        if not title or timestamp is None:
            return None

        # Ask HN and Show HN posts carry no external url; the discussion
        # page is the canonical location for those.
        url = raw.get("url") or f"https://news.ycombinator.com/item?id={story_id}"

        try:
            return build_item(
                source=self.name,
                source_type=self.source_type,
                topic_hint=self.topic_hint,
                url=url,
                title=title,
                body=strip_html(raw.get("text")),
                author=raw.get("by"),
                published_at=datetime.fromtimestamp(timestamp, tz=UTC),
                run_id=self.run_id,
                shortener_hosts=self.shortener_hosts,
                client=client if self.shortener_hosts else None,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("hackernews: item %s failed to normalize: %s", story_id, exc)
            return None
