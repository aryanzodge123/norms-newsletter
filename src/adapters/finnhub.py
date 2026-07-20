"""Finnhub market news adapter (SPEC 6.1). Keyed source.

The key comes from src.config.get_settings().finnhub_key, never from the
environment directly. A missing key raises a clear RuntimeError at
construction so the collector marks the run partial. The general-news
endpoint returns a bare JSON array. Registered disabled until the key is
set.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Iterable

import httpx

from ..config import get_settings
from .base import RawItem, build_item

log = logging.getLogger(__name__)

API_URL = "https://finnhub.io/api/v1/news"
TIMEOUT_SECONDS = 15.0


def parse_epoch(value) -> datetime | None:
    """Finnhub datetimes are unix seconds. Return None rather than guessing."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


class FinnhubAdapter:
    name = "finnhub"
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
        self.api_key = get_settings().finnhub_key
        if not self.api_key:
            raise RuntimeError(
                f"{self.name}: FINNHUB_KEY is not set. Enable this source only "
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
                params={"category": "general", "token": self.api_key},
            )
            response.raise_for_status()
            return self.parse(response.json(), since)
        finally:
            if owns_client:
                client.close()

    def parse(self, payload: list, since: datetime) -> list[RawItem]:
        """Normalize a decoded payload. Split out so tests run offline."""
        entries = payload or []
        items: list[RawItem] = []
        for entry in entries:
            if len(items) >= self.max_items:
                break
            item = self._normalize(entry)
            if item is None or item.published_at < since:
                continue
            items.append(item)
        return items

    def _normalize(self, entry: dict) -> RawItem | None:
        """A malformed entry is skipped, never fatal."""
        title = entry.get("headline")
        link = entry.get("url")
        published_at = parse_epoch(entry.get("datetime"))
        if not title or not link or published_at is None:
            log.warning("%s: skipping entry missing headline, url, or date", self.name)
            return None

        try:
            return build_item(
                source=self.name,
                source_type=self.source_type,
                topic_hint=self.topic_hint,
                url=link,
                title=title,
                body=entry.get("summary"),
                author=entry.get("source"),
                published_at=published_at,
                run_id=self.run_id,
                shortener_hosts=self.shortener_hosts,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: entry failed to normalize: %s", self.name, exc)
            return None
