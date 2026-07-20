"""FRED releases adapter (SPEC 6.1). Keyed source.

The key comes from src.config.get_settings().fred_key, never from the
environment directly. A missing key raises a clear RuntimeError at
construction so the collector marks the run partial. Registered disabled
until the key is set.

A FRED release has no article body or single timestamp, so each release
maps to a RawItem using its name as the title, its own link (or the FRED
release page for its id) as the url, and its realtime_start date as
published_at. A release with no usable date is skipped rather than guessed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Iterable

import httpx

from ..config import get_settings
from .base import RawItem, build_item

log = logging.getLogger(__name__)

API_URL = "https://api.stlouisfed.org/fred/releases"
RELEASE_PAGE = "https://fred.stlouisfed.org/release"
TIMEOUT_SECONDS = 15.0


def parse_release_date(value: str | None) -> datetime | None:
    """FRED dates are YYYY-MM-DD. Return None rather than guessing."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


class FREDAdapter:
    name = "fred"
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
        self.api_key = get_settings().fred_key
        if not self.api_key:
            raise RuntimeError(
                f"{self.name}: FRED_KEY is not set. Enable this source only "
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
                params={"api_key": self.api_key, "file_type": "json"},
            )
            response.raise_for_status()
            return self.parse(response.json(), since)
        finally:
            if owns_client:
                client.close()

    def parse(self, payload: dict, since: datetime) -> list[RawItem]:
        """Normalize a decoded payload. Split out so tests run offline."""
        releases = payload.get("releases") or []
        items: list[RawItem] = []
        for entry in releases:
            if len(items) >= self.max_items:
                break
            item = self._normalize(entry)
            if item is None or item.published_at < since:
                continue
            items.append(item)
        return items

    def _normalize(self, entry: dict) -> RawItem | None:
        """A malformed entry is skipped, never fatal."""
        title = entry.get("name")
        published_at = parse_release_date(entry.get("realtime_start"))
        if not title or published_at is None:
            log.warning("%s: skipping release missing name or date", self.name)
            return None

        link = entry.get("link")
        if not link:
            release_id = entry.get("id")
            if release_id is None:
                log.warning("%s: skipping release with no link or id", self.name)
                return None
            link = f"{RELEASE_PAGE}?rid={release_id}"

        try:
            return build_item(
                source=self.name,
                source_type=self.source_type,
                topic_hint=self.topic_hint,
                url=link,
                title=title,
                body=None,
                author=None,
                published_at=published_at,
                run_id=self.run_id,
                shortener_hosts=self.shortener_hosts,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: release failed to normalize: %s", self.name, exc)
            return None
