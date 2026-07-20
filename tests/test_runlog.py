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
