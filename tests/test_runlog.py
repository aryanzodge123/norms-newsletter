"""ops.run_log rows (SPEC section 8)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from src import runlog

RUN_ID = "20260719T110003Z-a4f2"
STARTED = datetime(2026, 7, 19, 11, 0, 0, tzinfo=UTC)
ENDED = datetime(2026, 7, 19, 11, 0, 12, tzinfo=UTC)


def collector_row(**overrides):
    row = dict(
        run_id=RUN_ID,
        job="collector",
        started_at=STARTED,
        ended_at=ENDED,
        status="success",
        items_in=61,
        items_out=54,
        adapter_metrics={"hackernews": {"items": 40, "errors": 0, "latency_ms": 812}},
    )
    row.update(overrides)
    return runlog.build_row(**row)


@pytest.fixture
def table(local_catalog):
    return runlog.ensure_table(local_catalog)


def test_row_has_the_spec_columns() -> None:
    assert set(collector_row()) == {
        "run_id",
        "job",
        "started_at",
        "ended_at",
        "status",
        "items_in",
        "items_out",
        "adapter_metrics",
        "ai_cost_estimate_usd",
        "readability_flag",
        "headline_repeat_flag",
        "notes",
        "run_date",
    }


def test_run_date_is_derived_from_started_at() -> None:
    assert collector_row()["run_date"] == STARTED.date()


def test_adapter_metrics_serialize_to_json() -> None:
    metrics = json.loads(collector_row()["adapter_metrics"])
    assert metrics["hackernews"]["latency_ms"] == 812


def test_non_collector_jobs_carry_no_adapter_metrics() -> None:
    row = runlog.build_row(
        run_id=RUN_ID,
        job="editor",
        started_at=STARTED,
        ended_at=ENDED,
        status="success",
        items_in=120,
        items_out=18,
        ai_cost_estimate_usd=0.42,
        readability_flag=False,
    )
    assert row["adapter_metrics"] is None
    assert row["ai_cost_estimate_usd"] == 0.42
    assert row["readability_flag"] is False


def test_rejects_an_unknown_job() -> None:
    with pytest.raises(ValueError, match="unknown job"):
        collector_row(job="nonsense")


def test_rejects_an_unknown_status() -> None:
    with pytest.raises(ValueError, match="unknown status"):
        collector_row(status="ok")


@pytest.mark.parametrize("status", ["success", "partial", "failed"])
def test_accepts_every_spec_status(status: str) -> None:
    assert collector_row(status=status)["status"] == status


def test_writes_a_row(table) -> None:
    runlog.write_row(table, collector_row())
    stored = table.scan().to_arrow().to_pylist()
    assert len(stored) == 1
    assert stored[0]["run_id"] == RUN_ID
    assert stored[0]["status"] == "success"
    assert stored[0]["ai_cost_estimate_usd"] is None


def test_a_partial_run_records_which_adapter_failed(table) -> None:
    """The degraded case SPEC section 8 exists to make visible."""
    runlog.write_row(
        table,
        collector_row(
            status="partial",
            adapter_metrics={
                "hackernews": {"items": 40, "errors": 0, "latency_ms": 812},
                "arstechnica": {"items": 0, "errors": 1, "latency_ms": 3001},
            },
            notes="adapters failed: arstechnica",
        ),
    )
    row = table.scan().to_arrow().to_pylist()[0]
    assert row["status"] == "partial"
    assert row["notes"] == "adapters failed: arstechnica"
    assert json.loads(row["adapter_metrics"])["arstechnica"]["errors"] == 1


# --------------------------------------------------------------------------
# Adding a column to a live table (SPEC 8)
# --------------------------------------------------------------------------
def test_added_column_is_applied_to_an_existing_table(local_catalog):
    """A table created before the column exists gets it on the next run.

    ensure_table runs immediately before every write_row, so migrating here
    leaves no window in which new code meets an old table.
    """
    table = runlog.ensure_table(local_catalog)
    assert "headline_repeat_flag" in table.schema().column_names


def test_ensure_table_is_idempotent(local_catalog):
    """add_column itself is not idempotent; ensure_table has to be.

    It runs on every job's every run, so a second call must be a no-op
    rather than raising "column already exists".
    """
    first = runlog.ensure_table(local_catalog)
    width = len(first.schema().fields)
    for _ in range(3):
        again = runlog.ensure_table(local_catalog)
    assert len(again.schema().fields) == width


def _pre_migration_table(catalog):
    """The table as it existed in production before the column was added."""
    from pyiceberg.schema import Schema

    from src.storage import ensure_namespace

    ensure_namespace(catalog, runlog.NAMESPACE)
    added = {name for name, _ in runlog._ADDED_COLUMNS}
    old = Schema(*[f for f in runlog.SCHEMA.fields if f.name not in added])
    return catalog.create_table_if_not_exists(
        runlog.TABLE_NAME, schema=old, partition_spec=runlog.PARTITION_SPEC
    )


def test_a_stale_handle_losing_the_race_is_not_an_error(local_catalog):
    """The real concurrency case, and it does not raise ValueError.

    The collector runs every 3h and the publish job at 6am, so two jobs can
    hold handles from before the migration. The loser commits against a
    changed schema and gets CommitFailedException, not the "already exists"
    ValueError a same-handle double-add would produce. The guard therefore
    checks the end state rather than the exception type.
    """
    _pre_migration_table(local_catalog)
    job_a = local_catalog.load_table(runlog.TABLE_NAME)
    job_b = local_catalog.load_table(runlog.TABLE_NAME)
    assert "headline_repeat_flag" not in job_a.schema().column_names

    migrated = runlog._ensure_added_columns(local_catalog, job_a)
    assert "headline_repeat_flag" in migrated.schema().column_names

    # job_b's handle predates that commit, which is the whole point.
    recovered = runlog._ensure_added_columns(local_catalog, job_b)
    assert "headline_repeat_flag" in recovered.schema().column_names
    runlog.write_row(recovered, collector_row())
    assert len(recovered.scan().to_arrow().to_pylist()) == 1


def test_write_row_survives_a_table_that_was_never_migrated(local_catalog):
    """Defence in depth: the row lands even without the column.

    Losing one field of observability is recoverable. Losing the row is not,
    because every job writes one in a finally block.
    """
    table = _pre_migration_table(local_catalog)
    runlog.write_row(table, collector_row(headline_repeat_flag=True))
    rows = table.scan().to_arrow().to_pylist()
    assert len(rows) == 1
    assert "headline_repeat_flag" not in rows[0]


def test_write_row_projects_onto_the_tables_real_columns(local_catalog):
    """Logging survives even if a column never reached this table.

    Every job writes its run_log row in a finally block, so losing the row
    is worse than losing one field of it.
    """
    table = runlog.ensure_table(local_catalog)
    row = collector_row()
    row["a_column_this_table_does_not_have"] = True
    runlog.write_row(table, row)
    rows = table.scan().to_arrow().to_pylist()
    assert len(rows) == 1
    assert rows[0]["run_id"] == row["run_id"]


def test_flag_round_trips(local_catalog):
    table = runlog.ensure_table(local_catalog)
    row = runlog.build_row(
        run_id=runlog.make_run_id(), job="editor",
        started_at=datetime.now(UTC), ended_at=datetime.now(UTC),
        status="partial", items_in=1, items_out=1,
        headline_repeat_flag=True,
    )
    runlog.write_row(table, row)
    assert table.scan().to_arrow().to_pylist()[0]["headline_repeat_flag"] is True
