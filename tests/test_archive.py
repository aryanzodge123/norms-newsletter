"""The archival job and the gold record (SPEC 6.9).

Everything here runs against the local sqlite catalog from conftest, so gold
tables are created and dropped for real without touching R2. What is pinned:
the day folds into gold, the month partition is compacted to a single file,
the daily bronze/silver partitions are dropped, a re-run is idempotent, and
old snapshots are expired.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import numpy as np
import pytest

from src import archive, bronze
from src.silver import table as silver_table
from src.silver.cluster import Cluster
from src.silver.score import ScoringResult

from tests.conftest import make_item

NOW = datetime(2026, 7, 25, 10, 0, tzinfo=UTC)


def seed_day(cat, day: date, *, headlines: list[str], scores: list[int]):
    """Write one day's bronze items and silver clusters (one cluster/item)."""
    bt = bronze.ensure_table(cat)
    items = [
        make_item(
            f"https://ex.com/{day.isoformat()}-{i}",
            title=headlines[i],
            body="grounding text " * 40,
            published_at=datetime(day.year, day.month, day.day, 9, i, tzinfo=UTC),
        ).model_copy(update={"ingest_date": day})
        for i in range(len(headlines))
    ]
    bronze.append_items(bt, items)

    st = silver_table.ensure_table(cat)
    rows = []
    for i, score in enumerate(scores):
        cluster = Cluster()
        cluster.add(items[i], np.ones(4, dtype="float32"))
        result = ScoringResult(
            score=score,
            rationale="r",
            confidence=0.9,
            topic="Technology",
            model_version="m",
            prompt_version="p",
            scored_at=datetime(day.year, day.month, day.day, 12, tzinfo=UTC),
            cost_usd=0.001,
        )
        rows.append(silver_table.build_row(cluster, result))
    silver_table.overwrite_partition(st, day, rows)
    return items, rows


def write_edition(editions_dir, day: date, cluster_ids: list[str], *, number=1):
    editions_dir.mkdir(parents=True, exist_ok=True)
    edition = {
        "edition_number": number,
        "edition_type": "normal",
        "sections": [{"stories": [{"cluster_id": cid} for cid in cluster_ids]}],
    }
    (editions_dir / f"{day.isoformat()}.json").write_text(json.dumps(edition))


def test_day_folds_into_gold_and_partitions_drop(local_catalog, tmp_path):
    cat = local_catalog
    day = date(2026, 7, 18)
    _, rows = seed_day(cat, day, headlines=["A", "B", "C"], scores=[7, 5, 3])
    eds = tmp_path / "editions"
    write_edition(eds, day, [rows[0]["cluster_id"]])

    metrics = archive.archive_day(cat, day, now=NOW, editions_dir=eds, snapshot_expiry_days=7)

    assert metrics["raw_written"] == 3
    assert metrics["clusters_written"] == 3
    assert metrics["editions_written"] == 1
    assert metrics["edition_missing"] is False

    # Gold holds the record.
    assert len(cat.load_table(archive.RAW_ITEMS).scan().to_arrow()) == 3
    assert len(cat.load_table(archive.STORY_CLUSTERS).scan().to_arrow()) == 3
    ged = cat.load_table(archive.EDITIONS).scan().to_arrow().to_pylist()
    assert len(ged) == 1
    assert ged[0]["edition_type"] == "normal"
    assert json.loads(ged[0]["edition_json"])["edition_number"] == 1

    # Daily partitions are gone (fresh reload, not the stale write handle).
    assert bronze.read_partition(cat.load_table(bronze.TABLE_NAME), day) == []
    assert silver_table.read_partition(cat.load_table(silver_table.TABLE_NAME), day) == {}


def test_rerun_is_idempotent(local_catalog, tmp_path):
    cat = local_catalog
    day = date(2026, 7, 18)
    _, rows = seed_day(cat, day, headlines=["A", "B"], scores=[7, 5])
    eds = tmp_path / "editions"
    write_edition(eds, day, [rows[0]["cluster_id"]])

    archive.archive_day(cat, day, now=NOW, editions_dir=eds, snapshot_expiry_days=7)
    # Second pass: bronze/silver already dropped, so nothing new is written
    # and gold is unchanged.
    metrics = archive.archive_day(cat, day, now=NOW, editions_dir=eds, snapshot_expiry_days=7)

    assert metrics["raw_written"] == 0
    assert metrics["clusters_written"] == 0
    assert len(cat.load_table(archive.RAW_ITEMS).scan().to_arrow()) == 2


def test_month_is_compacted_to_one_file(local_catalog, tmp_path):
    cat = local_catalog
    eds = tmp_path / "editions"
    for day in (date(2026, 7, 18), date(2026, 7, 19), date(2026, 7, 20)):
        _, rows = seed_day(cat, day, headlines=[f"{day} A", f"{day} B"], scores=[7, 4])
        write_edition(eds, day, [rows[0]["cluster_id"]])
        archive.archive_day(cat, day, now=NOW, editions_dir=eds, snapshot_expiry_days=7)

    gold = cat.load_table(archive.RAW_ITEMS)
    assert len(gold.scan().to_arrow()) == 6  # 3 days x 2 items
    files = {task.file.file_path for task in gold.scan().plan_files()}
    assert len(files) == 1  # one month, one file: compacted


def test_old_snapshots_are_expired(local_catalog, tmp_path):
    cat = local_catalog
    day = date(2026, 7, 18)
    _, rows = seed_day(cat, day, headlines=["A", "B"], scores=[7, 5])
    eds = tmp_path / "editions"
    write_edition(eds, day, [rows[0]["cluster_id"]])
    archive.archive_day(cat, day, now=NOW, editions_dir=eds, snapshot_expiry_days=7)

    before = len(cat.load_table(archive.RAW_ITEMS).metadata.snapshots)

    # A far-future run makes the 7-day cutoff land after every existing
    # snapshot, so all but the protected current snapshot expire.
    future = datetime(2027, 1, 1, 10, 0, tzinfo=UTC)
    archive.archive_day(cat, day, now=future, editions_dir=eds, snapshot_expiry_days=7)

    after = len(cat.load_table(archive.RAW_ITEMS).metadata.snapshots)
    assert after == 1
    assert after <= before


def test_dry_run_writes_nothing(local_catalog, tmp_path, capsys):
    cat = local_catalog
    day = date(2026, 7, 18)
    seed_day(cat, day, headlines=["A", "B"], scores=[7, 5])

    metrics = archive.archive_day(
        cat, day, now=NOW, editions_dir=tmp_path / "editions", dry_run=True
    )

    assert metrics == {"bronze": 2, "silver": 2, "edition": False}
    # Gold was never created; the daily partition is untouched.
    with pytest.raises(Exception):
        cat.load_table(archive.RAW_ITEMS)
    assert len(bronze.read_partition(cat.load_table(bronze.TABLE_NAME), day)) == 2


def test_missing_edition_reports_but_still_archives(local_catalog, tmp_path):
    cat = local_catalog
    day = date(2026, 7, 18)
    seed_day(cat, day, headlines=["A"], scores=[7])

    metrics = archive.archive_day(
        cat, day, now=NOW, editions_dir=tmp_path / "empty", snapshot_expiry_days=7
    )

    assert metrics["edition_missing"] is True
    assert metrics["editions_written"] == 0
    # The data still folds into gold; only the edition blob is absent.
    assert len(cat.load_table(archive.RAW_ITEMS).scan().to_arrow()) == 1
