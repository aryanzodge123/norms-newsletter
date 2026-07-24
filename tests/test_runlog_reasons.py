"""Reason codes and the degraded query (SPEC section 8, decision #27).

The codes are the machine-readable half of a `partial`/`failed` run: `notes`
carries the prose, `reasons` drives the degraded alert. These pin the storage
shape and the `is_degraded` boundary that the alert depends on.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from src import runlog


def _row(catalog):
    return runlog.ensure_table(catalog).scan().to_arrow().to_pylist()


def test_reason_dedupes_and_preserves_first_order():
    rec = runlog.RunRecord(run_id="x", job="editor", started_at=datetime.now(UTC))
    rec.reason(runlog.REASON_THIN_GROUNDING)
    rec.reason(runlog.REASON_THIN_GROUNDING)
    rec.reason(runlog.REASON_HEADLINE_REPEAT)
    assert rec.reasons == [runlog.REASON_THIN_GROUNDING, runlog.REASON_HEADLINE_REPEAT]


def test_build_row_stores_sorted_json():
    now = datetime.now(UTC)
    row = runlog.build_row(
        run_id="x", job="editor", started_at=now, ended_at=now,
        status="partial", items_in=1, items_out=1,
        reasons=["thin_grounding", "assembly_fallback"],
    )
    assert row["reasons"] == json.dumps(["assembly_fallback", "thin_grounding"])


def test_build_row_none_reasons_stores_null():
    now = datetime.now(UTC)
    row = runlog.build_row(
        run_id="x", job="editor", started_at=now, ended_at=now,
        status="success", items_in=0, items_out=0,
    )
    assert row["reasons"] is None


def test_build_row_rejects_an_unknown_code():
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="unknown reason code"):
        runlog.build_row(
            run_id="x", job="editor", started_at=now, ended_at=now,
            status="partial", items_in=1, items_out=1, reasons=["made_up"],
        )


@pytest.mark.parametrize(
    "reasons,expected",
    [
        (["assembly_fallback"], True),
        (["editor_invalid_fallback"], True),
        (["thin_grounding", "assembly_fallback"], True),  # any degraded -> degraded
        (["thin_day_fallback"], False),  # a thin day is correct behavior
        (["thin_grounding"], False),
        (["headline_repeat"], False),
        ([], False),
        (None, False),
    ],
)
def test_is_degraded_boundary(reasons, expected):
    assert runlog.is_degraded(reasons) is expected


def test_is_degraded_accepts_the_stored_json_string():
    assert runlog.is_degraded('["assembly_fallback"]') is True
    assert runlog.is_degraded('["thin_grounding"]') is False
    assert runlog.is_degraded("not json") is False


def test_degraded_reasons_are_a_subset_of_all_reasons():
    assert runlog.DEGRADED_REASONS <= runlog.REASONS


def test_logged_run_persists_reasons(local_catalog):
    with runlog.logged_run("editor", catalog_factory=lambda: local_catalog) as rec:
        rec.status = "partial"
        rec.reason(runlog.REASON_ASSEMBLY_FALLBACK)
        rec.note("fallback edition: ValueError during assembly")

    row = _row(local_catalog)[0]
    assert row["status"] == "partial"
    assert runlog.is_degraded(row["reasons"]) is True


def test_a_raise_records_run_failed(local_catalog):
    with runlog.logged_run("silver", catalog_factory=lambda: local_catalog):
        raise RuntimeError("boom")

    row = _row(local_catalog)[0]
    assert row["status"] == "failed"
    assert runlog.REASON_RUN_FAILED in json.loads(row["reasons"])
    # A crash is failed, not degraded: degraded is about a thin publication.
    assert runlog.is_degraded(row["reasons"]) is False


def test_migration_adds_reasons_to_a_preexisting_table(local_catalog):
    # A table created before the reasons column existed still accepts a row,
    # and ensure_table brings it up to schema. Mirrors the headline_repeat_flag
    # migration proven in test_runlog.py.
    import pyarrow as pa
    from pyiceberg.schema import Schema
    from pyiceberg.types import (
        DateType, IntegerType, NestedField, StringType, TimestamptzType,
    )
    from src.storage import ensure_namespace

    ensure_namespace(local_catalog, runlog.NAMESPACE)
    old_schema = Schema(
        NestedField(1, "run_id", StringType(), required=True),
        NestedField(2, "job", StringType(), required=True),
        NestedField(3, "started_at", TimestamptzType(), required=True),
        NestedField(4, "ended_at", TimestamptzType(), required=True),
        NestedField(5, "status", StringType(), required=True),
        NestedField(6, "items_in", IntegerType(), required=True),
        NestedField(7, "items_out", IntegerType(), required=True),
        NestedField(12, "run_date", DateType(), required=True),
    )
    local_catalog.create_table(runlog.TABLE_NAME, schema=old_schema)

    table = runlog.ensure_table(local_catalog)  # migrates
    assert "reasons" in table.schema().column_names

    now = datetime.now(UTC)
    runlog.write_row(table, runlog.build_row(
        run_id="x", job="editor", started_at=now, ended_at=now,
        status="partial", items_in=1, items_out=1,
        reasons=["assembly_fallback"],
    ))
    rows = _row(local_catalog)
    assert rows[0]["reasons"] == json.dumps(["assembly_fallback"])
