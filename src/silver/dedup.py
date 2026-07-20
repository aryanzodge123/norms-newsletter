"""Silver dedup (SPEC 6.4a): drop duplicate item_ids and same-day
canonical_urls.

Bronze already rejects duplicate item_ids at write time (SPEC 6.3), so
the item_id pass here is belt and braces. The canonical_url pass is the
one that earns its keep: SPEC 6.1 allows the shortener_hosts list to
change mid-day, and says the same article fetched before and after such a
change may land under two item_ids. That is an acceptable duplicate in
bronze. This is where it gets absorbed, before it can become two clusters.

Same-day means same ingest_date. Two items sharing a canonical_url across
different days are two legitimate rows: the story was collected twice on
two days, and each day's edition is entitled to its own.
"""

from __future__ import annotations

import logging

from ..adapters.base import RawItem

log = logging.getLogger(__name__)


def _sort_key(item: RawItem) -> tuple:
    """Earliest published wins, item_id breaking ties deterministically."""
    return (item.published_at, item.item_id)


def dedup(items: list[RawItem]) -> list[RawItem]:
    """Collapse duplicate item_ids, then same-day canonical_urls.

    Returns items in published_at order, which is also the order the
    clusterer needs (SPEC 6.4b greedy pass, see cluster.py).
    """
    if not items:
        return []

    by_id: dict[str, RawItem] = {}
    for item in sorted(items, key=_sort_key):
        by_id.setdefault(item.item_id, item)

    by_url: dict[tuple, RawItem] = {}
    for item in sorted(by_id.values(), key=_sort_key):
        by_url.setdefault((item.ingest_date, item.canonical_url), item)

    kept = sorted(by_url.values(), key=_sort_key)
    dropped = len(items) - len(kept)
    if dropped:
        log.info("dedup: kept %d items, dropped %d duplicates", len(kept), dropped)
    return kept
