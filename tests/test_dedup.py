"""Silver dedup (SPEC 6.4a).

The case that earns this layer: SPEC 6.1 lets shortener_hosts change
mid-day, which can put the same article in bronze under two item_ids.
Bronze accepts that. Silver must not turn it into two clusters.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.silver.dedup import dedup
from tests.conftest import FETCHED, make_item

EARLIER = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
LATER = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)


def test_empty_input() -> None:
    assert dedup([]) == []


def test_keeps_distinct_items() -> None:
    items = [make_item("https://example.com/a"), make_item("https://example.com/b")]
    assert len(dedup(items)) == 2


def test_collapses_duplicate_item_ids() -> None:
    item = make_item("https://example.com/a")
    assert len(dedup([item, item, item])) == 1


def test_collapses_same_day_canonical_urls() -> None:
    """Two item_ids, one article. The shortener_hosts case from SPEC 6.1."""
    first = make_item("https://example.com/a", published_at=EARLIER)
    second = make_item("https://example.com/a", published_at=LATER)
    assert first.item_id != second.item_id
    assert first.canonical_url == second.canonical_url

    kept = dedup([first, second])
    assert len(kept) == 1
    assert kept[0].item_id == first.item_id, "earliest published should win"


def test_earliest_published_wins_regardless_of_input_order() -> None:
    first = make_item("https://example.com/a", published_at=EARLIER)
    second = make_item("https://example.com/a", published_at=LATER)
    assert dedup([second, first])[0].item_id == first.item_id


def test_same_url_on_different_days_is_kept() -> None:
    """Each day's edition is entitled to its own copy.

    A genuinely re-published story has a later published_at, so it also
    has a different item_id (SPEC 6.1). The same item_id fetched twice is
    the same item, and bronze would have rejected the second copy anyway.
    """
    today = make_item("https://example.com/a", published_at=LATER)
    yesterday = make_item(
        "https://example.com/a",
        published_at=EARLIER - timedelta(days=1),
        fetched_at=FETCHED - timedelta(days=1),
    )
    assert today.ingest_date != yesterday.ingest_date
    assert today.item_id != yesterday.item_id

    assert len(dedup([today, yesterday])) == 2


def test_the_same_item_id_collapses_even_across_days() -> None:
    """Same canonical_url and published_at is the same item, full stop."""
    today = make_item("https://example.com/a")
    refetched = make_item("https://example.com/a", fetched_at=FETCHED - timedelta(days=1))
    assert today.item_id == refetched.item_id

    assert len(dedup([today, refetched])) == 1


def test_tracking_params_already_collapsed_by_canonicalization() -> None:
    plain = make_item("https://example.com/a")
    tracked = make_item("https://example.com/a?utm_source=rss")
    assert len(dedup([plain, tracked])) == 1


def test_output_is_ordered_by_published_at() -> None:
    """cluster() depends on this ordering for stable cluster_ids."""
    items = [
        make_item("https://example.com/c", published_at=LATER),
        make_item("https://example.com/a", published_at=EARLIER),
        make_item("https://example.com/b", published_at=datetime(2026, 7, 19, 9, tzinfo=UTC)),
    ]
    kept = dedup(items)
    assert [i.published_at for i in kept] == sorted(i.published_at for i in kept)


def test_ties_break_deterministically() -> None:
    same_time = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
    items = [
        make_item("https://example.com/a", published_at=same_time),
        make_item("https://example.com/b", published_at=same_time),
    ]
    assert [i.item_id for i in dedup(items)] == [i.item_id for i in dedup(list(reversed(items)))]
