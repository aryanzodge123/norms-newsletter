"""bronze.raw_items writes (SPEC 6.3), against a local Iceberg catalog.

The property that matters: the collector is safe to run twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src import bronze
from src.adapters.base import build_item

RUN_ID = "20260719T110003Z-a4f2"
FETCHED = datetime(2026, 7, 19, 11, 0, 0, tzinfo=UTC)


def make_item(url: str, *, title: str = "A story", fetched_at=FETCHED, **kwargs):
    return build_item(
        source="hackernews",
        source_type="api",
        topic_hint="tech",
        url=url,
        title=title,
        body="Some body text.",
        author="pg",
        published_at=datetime(2026, 7, 19, 9, 0, tzinfo=UTC),
        run_id=RUN_ID,
        fetched_at=fetched_at,
        **kwargs,
    )


@pytest.fixture
def table(local_catalog):
    return bronze.ensure_table(local_catalog)


def row_count(table) -> int:
    return table.scan().to_arrow().num_rows


def test_ensure_table_is_idempotent(local_catalog) -> None:
    first = bronze.ensure_table(local_catalog)
    second = bronze.ensure_table(local_catalog)
    assert first.name() == second.name()


def test_appends_rows(table) -> None:
    written, skipped = bronze.append_items(
        table, [make_item("https://example.com/a"), make_item("https://example.com/b")]
    )
    assert (written, skipped) == (2, 0)
    assert row_count(table) == 2


def test_running_twice_writes_nothing_the_second_time(table) -> None:
    """Idempotency, the whole point of SPEC 6.2."""
    items = [make_item("https://example.com/a"), make_item("https://example.com/b")]
    bronze.append_items(table, items)

    written, skipped = bronze.append_items(table, items)
    assert (written, skipped) == (0, 2)
    assert row_count(table) == 2


def test_deduplicates_within_a_single_batch(table) -> None:
    """Two sources surfacing the same canonical_url in one run."""
    written, skipped = bronze.append_items(
        table,
        [
            make_item("https://example.com/a"),
            make_item("https://example.com/a?utm_source=rss"),
        ],
    )
    assert (written, skipped) == (1, 1)
    assert row_count(table) == 1


def test_a_second_run_still_writes_genuinely_new_items(table) -> None:
    bronze.append_items(table, [make_item("https://example.com/a")])
    written, skipped = bronze.append_items(
        table, [make_item("https://example.com/a"), make_item("https://example.com/c")]
    )
    assert (written, skipped) == (1, 1)
    assert row_count(table) == 2


def test_empty_batch_is_a_no_op(table) -> None:
    assert bronze.append_items(table, []) == (0, 0)
    assert row_count(table) == 0


def test_dedup_looks_across_partitions_the_batch_touches(table) -> None:
    """A batch spanning two ingest_dates dedups against both."""
    yesterday = FETCHED - timedelta(days=1)
    old = make_item("https://example.com/a", fetched_at=yesterday)
    bronze.append_items(table, [old])

    written, skipped = bronze.append_items(
        table, [old, make_item("https://example.com/b")]
    )
    assert (written, skipped) == (1, 1)
    assert row_count(table) == 2


def test_stored_columns_match_the_spec_schema(table) -> None:
    bronze.append_items(table, [make_item("https://example.com/a")])
    stored = table.scan().to_arrow()
    assert set(stored.column_names) == {
        "item_id",
        "source",
        "source_type",
        "topic_hint",
        "url",
        "canonical_url",
        "title",
        "body_excerpt",
        "author",
        "published_at",
        "fetched_at",
        "run_id",
        "ingest_date",
    }
    row = stored.to_pylist()[0]
    assert row["run_id"] == RUN_ID
    assert row["ingest_date"] == FETCHED.date()


def test_a_null_author_round_trips(table) -> None:
    item = make_item("https://example.com/a")
    item = item.model_copy(update={"author": None})
    bronze.append_items(table, [item])
    assert table.scan().to_arrow().to_pylist()[0]["author"] is None
