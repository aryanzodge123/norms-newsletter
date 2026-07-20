"""Federal Register JSON API adapter (SPEC 6.1). Free, no key needed.

Documents ordered newest first. The endpoint is fixed here because the
ordering and field selection belong to this adapter. parse() takes the
already-decoded JSON payload so tests drive it from a fixture dict without
network.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Iterable

import httpx

from .base import RawItem, build_item

log = logging.getLogger(__name__)

API_URL = "https://www.federalregister.gov/api/v1/documents.json"
TIMEOUT_SECONDS = 15.0


def parse_publication_date(value: str | None) -> datetime | None:
    """Federal Register dates are YYYY-MM-DD. Return None rather than guess."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


class FederalRegisterAdapter:
    name = "federal_register"
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

    def fetch(self, since: datetime) -> list[RawItem]:
        owns_client = self._client is None
        client = self._client or httpx.Client(
            timeout=TIMEOUT_SECONDS, follow_redirects=True
        )
        try:
            response = client.get(
                API_URL,
                params={"order": "newest", "per_page": self.max_items},
            )
            response.raise_for_status()
            return self.parse(response.json(), since)
        finally:
            if owns_client:
                client.close()

    def parse(self, payload: dict, since: datetime) -> list[RawItem]:
        """Normalize a decoded payload. Split out so tests run offline."""
        results = payload.get("results") or []
        items: list[RawItem] = []
        for entry in results:
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
        link = entry.get("html_url")
        published_at = parse_publication_date(entry.get("publication_date"))
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
                body=entry.get("abstract"),
                author=entry.get("agencies", [{}])[0].get("name")
                if entry.get("agencies")
                else None,
                published_at=published_at,
                run_id=self.run_id,
                shortener_hosts=self.shortener_hosts,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: entry failed to normalize: %s", self.name, exc)
            return None
