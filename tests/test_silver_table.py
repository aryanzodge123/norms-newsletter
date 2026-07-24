"""silver.story_clusters writes (SPEC 6.4), against a local Iceberg catalog.

The property that matters: a silver run rebuilds a day rather than
appending to it, so running it twice leaves one copy of each cluster.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from pyiceberg.exceptions import CommitFailedException

from src.silver import table as silver_table
from src.silver.cluster import Cluster
from src.silver.score import ScoringResult
from tests.conftest import FETCHED, make_item

SCORED = ScoringResult(
    score=7,
    topic="Regulation",
    rationale="A final rule with a compliance date.",
    confidence=0.85,
    model_version="claude-haiku-4-5-20251001",
    prompt_version="scoring_v1",
    scored_at=datetime(2026, 7, 19, 11, 30, tzinfo=UTC),
    cost_usd=0.0001,
)

NULL_SCORED = ScoringResult(
    score=None,
    topic=None,
    rationale=None,
    confidence=None,
    model_version="claude-haiku-4-5-20251001",
    prompt_version="scoring_v1",
    scored_at=datetime(2026, 7, 19, 11, 30, tzinfo=UTC),
    cost_usd=0.0002,
)


def a_cluster(*urls: str, fetched_at=FETCHED, title: str = "A story") -> Cluster:
    c = Cluster()
    for i, url in enumerate(urls):
        c.add(
            make_item(url, title=title, source=f"source{i}", fetched_at=fetched_at),
            np.array([1.0]),
        )
    return c


@pytest.fixture
def table(local_catalog):
    return silver_table.ensure_table(local_catalog)


def row_count(table) -> int:
    return table.scan().to_arrow().num_rows


def test_ensure_table_is_idempotent(local_catalog) -> None:
    first = silver_table.ensure_table(local_catalog)
    second = silver_table.ensure_table(local_catalog)
    assert first.name() == second.name()


def test_writes_a_partition(table) -> None:
    cluster = a_cluster("https://example.com/a")
    written = silver_table.overwrite_partition(
        table, FETCHED.date(), [silver_table.build_row(cluster, SCORED)]
    )
    assert written == 1
    assert row_count(table) == 1


def test_running_twice_replaces_rather_than_appends(table) -> None:
    """The idempotency proof for SPEC 6.4's rebuild strategy."""
    rows = [silver_table.build_row(a_cluster("https://example.com/a"), SCORED)]
    silver_table.overwrite_partition(table, FETCHED.date(), rows)
    silver_table.overwrite_partition(table, FETCHED.date(), rows)
    assert row_count(table) == 1


def test_a_rebuild_drops_clusters_that_no_longer_exist(table) -> None:
    first = [
        silver_table.build_row(a_cluster("https://example.com/a"), SCORED),
        silver_table.build_row(a_cluster("https://example.com/b"), SCORED),
    ]
    silver_table.overwrite_partition(table, FETCHED.date(), first)
    assert row_count(table) == 2

    silver_table.overwrite_partition(table, FETCHED.date(), first[:1])
    assert row_count(table) == 1


def test_overwriting_one_day_leaves_another_alone(table) -> None:
    yesterday = FETCHED - timedelta(days=1)
    silver_table.overwrite_partition(
        table,
        yesterday.date(),
        [silver_table.build_row(a_cluster("https://example.com/old", fetched_at=yesterday), SCORED)],
    )
    silver_table.overwrite_partition(
        table,
        FETCHED.date(),
        [silver_table.build_row(a_cluster("https://example.com/a"), SCORED)],
    )
    assert row_count(table) == 2


def test_an_empty_result_leaves_the_partition_untouched(table) -> None:
    """A run that found nothing must not silently erase a good partition."""
    silver_table.overwrite_partition(
        table, FETCHED.date(), [silver_table.build_row(a_cluster("https://example.com/a"), SCORED)]
    )
    assert silver_table.overwrite_partition(table, FETCHED.date(), []) == 0
    assert row_count(table) == 1


def test_overwrite_retries_after_a_lost_commit_race(table, monkeypatch) -> None:
    """SPEC 6.4 / decision #30: a lost commit race reloads and retries.

    The first commit raises as if a concurrent writer had moved the snapshot;
    the retry refreshes the handle and lands the rows.
    """
    monkeypatch.setattr(silver_table.time, "sleep", lambda _s: None)

    real_overwrite = table.overwrite
    real_refresh = table.refresh
    calls = {"overwrite": 0, "refresh": 0}

    def flaky_overwrite(*args, **kwargs):
        calls["overwrite"] += 1
        if calls["overwrite"] == 1:
            raise CommitFailedException("Branch or tag `main`'s snapshot has changed")
        return real_overwrite(*args, **kwargs)

    def counting_refresh(*args, **kwargs):
        calls["refresh"] += 1
        return real_refresh(*args, **kwargs)

    monkeypatch.setattr(table, "overwrite", flaky_overwrite)
    monkeypatch.setattr(table, "refresh", counting_refresh)

    rows = [silver_table.build_row(a_cluster("https://example.com/a"), SCORED)]
    written = silver_table.overwrite_partition(table, FETCHED.date(), rows)

    assert written == 1
    assert calls["overwrite"] == 2
    assert calls["refresh"] == 1
    assert row_count(table) == 1


def test_overwrite_reraises_when_retries_are_exhausted(table, monkeypatch) -> None:
    """Every attempt loses the race, so write_failed stays reachable in run_silver."""
    monkeypatch.setattr(silver_table.time, "sleep", lambda _s: None)

    calls = {"overwrite": 0}

    def always_conflicts(*args, **kwargs):
        calls["overwrite"] += 1
        raise CommitFailedException("Branch or tag `main`'s snapshot has changed")

    monkeypatch.setattr(table, "overwrite", always_conflicts)

    rows = [silver_table.build_row(a_cluster("https://example.com/a"), SCORED)]
    with pytest.raises(CommitFailedException):
        silver_table.overwrite_partition(table, FETCHED.date(), rows)

    assert calls["overwrite"] == silver_table.OVERWRITE_MAX_ATTEMPTS


def test_stored_columns_match_the_spec_schema(table) -> None:
    cluster = a_cluster("https://example.com/a", "https://example.com/b")
    silver_table.overwrite_partition(
        table, FETCHED.date(), [silver_table.build_row(cluster, SCORED)]
    )
    stored = table.scan().to_arrow().to_pylist()[0]
    assert set(stored) == {
        "cluster_id",
        "ingest_date",
        "topic",
        "headline",
        "summary_seed",
        "member_ids",
        "member_count",
        "sources",
        "score",
        "rationale",
        "confidence",
        "model_version",
        "prompt_version",
        "scored_at",
    }
    assert stored["cluster_id"] == cluster.cluster_id
    assert stored["member_count"] == 2
    assert stored["sources"] == ["source0", "source1"]
    assert stored["score"] == 7


def test_a_null_score_round_trips(table) -> None:
    silver_table.overwrite_partition(
        table,
        FETCHED.date(),
        [silver_table.build_row(a_cluster("https://example.com/a"), NULL_SCORED)],
    )
    stored = table.scan().to_arrow().to_pylist()[0]
    assert stored["score"] is None
    assert stored["topic"] is None
    assert stored["model_version"] == "claude-haiku-4-5-20251001"


def test_headline_and_summary_seed_come_from_the_seed_member(table) -> None:
    """Rule zero: these are derived by code, never written by the model."""
    cluster = a_cluster("https://example.com/a", title="The seed headline")
    row = silver_table.build_row(cluster, SCORED)
    assert row["headline"] == "The seed headline"
    assert row["summary_seed"] == cluster.seed.body_excerpt[:500].strip()


def test_summary_seed_is_bounded(table) -> None:
    c = Cluster()
    c.add(make_item("https://example.com/a", body="y" * 2000), np.array([1.0]))
    assert len(silver_table.build_row(c, SCORED)["summary_seed"]) == 500


def test_read_partition_keys_by_cluster_id(table) -> None:
    cluster = a_cluster("https://example.com/a")
    silver_table.overwrite_partition(
        table, FETCHED.date(), [silver_table.build_row(cluster, SCORED)]
    )
    stored = silver_table.read_partition(table, FETCHED.date())
    assert set(stored) == {cluster.cluster_id}
    assert stored[cluster.cluster_id]["member_count"] == 1


def test_read_partition_of_an_empty_day(table) -> None:
    assert silver_table.read_partition(table, FETCHED.date()) == {}
