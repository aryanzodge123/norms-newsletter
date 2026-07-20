"""CISA cybersecurity advisories adapter (SPEC 6.1). Free, no key needed.

A thin subclass of the generic RSS adapter with the advisories feed URL
fixed in code, so the source needs no feed_url in the registry. All the
parsing behavior (offline parse(), malformed-entry skipping, since filter,
max_items) is inherited unchanged.
"""

from __future__ import annotations

from typing import Iterable

import httpx

from .rss import RSSAdapter

FEED_URL = "https://www.cisa.gov/cybersecurity-advisories/all.xml"


class CISAAdapter(RSSAdapter):
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
        super().__init__(
            topic_hint=topic_hint,
            max_items=max_items,
            run_id=run_id,
            name=name or "cisa",
            feed_url=feed_url or FEED_URL,
            shortener_hosts=shortener_hosts,
            client=client,
        )
