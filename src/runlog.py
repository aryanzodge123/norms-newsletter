"""ops.run_log: one row per job run (SPEC section 8).

Written by every job, including failed ones. A job that cannot write its
own row is itself a failure, surfaced by the healthchecks.io dead man's
switch rather than by this table.
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime

import pyarrow as pa
from pyiceberg.catalog import Catalog
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.table import Table
from pyiceberg.transforms import IdentityTransform
from pyiceberg.types import (
    BooleanType,
    DateType,
    DoubleType,
    IntegerType,
    NestedField,
    StringType,
    TimestamptzType,
)

from .storage import ensure_namespace

log = logging.getLogger(__name__)

NAMESPACE = "ops"
TABLE_NAME = "ops.run_log"

JOBS = frozenset(
    {"collector", "silver", "editor", "writer", "audio", "site", "archive"}
)
STATUSES = frozenset({"success", "partial", "failed"})

RUN_ID_FORMAT = "%Y%m%dT%H%M%SZ"

SCHEMA = Schema(
    NestedField(1, "run_id", StringType(), required=True),
    NestedField(2, "job", StringType(), required=True),
    NestedField(3, "started_at", TimestamptzType(), required=True),
    NestedField(4, "ended_at", TimestamptzType(), required=True),
    NestedField(5, "status", StringType(), required=True),
    NestedField(6, "items_in", IntegerType(), required=True),
    NestedField(7, "items_out", IntegerType(), required=True),
    NestedField(8, "adapter_metrics", StringType(), required=False),
    NestedField(9, "ai_cost_estimate_usd", DoubleType(), required=False),
    NestedField(10, "readability_flag", BooleanType(), required=False),
    NestedField(11, "notes", StringType(), required=False),
    NestedField(12, "run_date", DateType(), required=True),
    NestedField(13, "headline_repeat_flag", BooleanType(), required=False),
)

PARTITION_SPEC = PartitionSpec(
    PartitionField(
        source_id=12, field_id=1000, transform=IdentityTransform(), name="run_date"
    )
)

ARROW_SCHEMA = pa.schema(
    [
        pa.field("run_id", pa.string(), nullable=False),
        pa.field("job", pa.string(), nullable=False),
        pa.field("started_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("ended_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("items_in", pa.int32(), nullable=False),
        pa.field("items_out", pa.int32(), nullable=False),
        pa.field("adapter_metrics", pa.string(), nullable=True),
        pa.field("ai_cost_estimate_usd", pa.float64(), nullable=True),
        pa.field("readability_flag", pa.bool_(), nullable=True),
        pa.field("notes", pa.string(), nullable=True),
        pa.field("run_date", pa.date32(), nullable=False),
        pa.field("headline_repeat_flag", pa.bool_(), nullable=True),
    ]
)


def make_run_id(now: datetime | None = None) -> str:
    """UTC timestamp plus 4 random hex chars, per SPEC 6.1.

    Example: 20260719T110003Z-a4f2
    """
    now = (now or datetime.now(UTC)).astimezone(UTC)
    return f"{now.strftime(RUN_ID_FORMAT)}-{secrets.token_hex(2)}"


def ensure_table(catalog: Catalog) -> Table:
    ensure_namespace(catalog, NAMESPACE)
    table = catalog.create_table_if_not_exists(
        TABLE_NAME, schema=SCHEMA, partition_spec=PARTITION_SPEC
    )
    return _ensure_added_columns(catalog, table)


# Columns added to SCHEMA after the table was first created in production.
# create_table_if_not_exists returns the existing table untouched, so an
# added column has to be applied to a live table explicitly.
_ADDED_COLUMNS: tuple[tuple[str, BooleanType], ...] = (
    ("headline_repeat_flag", BooleanType()),
)


def _ensure_added_columns(catalog: Catalog, table: Table) -> Table:
    """Bring a live table up to SCHEMA. Idempotent and concurrency-safe.

    Runs on every job's every run, because every job calls ensure_table
    immediately before write_row. That placement is deliberate: it leaves no
    window in which new code meets an old table.

    The guard checks the end state rather than the exception type, which
    matters more than it looks. `add_column` raises ValueError when the
    column already exists on this handle, but the real race, a job holding a
    handle from before another job migrated, raises CommitFailedException
    instead. Catching either by name would miss the other, so any failure is
    followed by a re-read: if the column is there now, someone else did the
    work, and if it is not, the failure was real and must surface.
    """
    missing = [
        (name, kind)
        for name, kind in _ADDED_COLUMNS
        if name not in table.schema().column_names
    ]
    if not missing:
        return table
    for name, kind in missing:
        try:
            with table.update_schema() as update:
                update.add_column(name, kind, required=False)
        except Exception:
            fresh = catalog.load_table(TABLE_NAME)
            if name not in fresh.schema().column_names:
                raise
            log.info("run_log column %s was added by another job", name)
        table = catalog.load_table(TABLE_NAME)
    return table


def build_row(
    *,
    run_id: str,
    job: str,
    started_at: datetime,
    ended_at: datetime,
    status: str,
    items_in: int,
    items_out: int,
    adapter_metrics: dict | None = None,
    ai_cost_estimate_usd: float | None = None,
    readability_flag: bool | None = None,
    headline_repeat_flag: bool | None = None,
    notes: str | None = None,
) -> dict:
    """Validate and shape one run_log row (SPEC section 8)."""
    if job not in JOBS:
        raise ValueError(f"unknown job {job!r}, expected one of {sorted(JOBS)}")
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}, expected one of {sorted(STATUSES)}")

    return {
        "run_id": run_id,
        "job": job,
        "started_at": started_at.astimezone(UTC),
        "ended_at": ended_at.astimezone(UTC),
        "status": status,
        "items_in": int(items_in),
        "items_out": int(items_out),
        "adapter_metrics": json.dumps(adapter_metrics, sort_keys=True)
        if adapter_metrics is not None
        else None,
        "ai_cost_estimate_usd": ai_cost_estimate_usd,
        "readability_flag": readability_flag,
        "headline_repeat_flag": headline_repeat_flag,
        "notes": notes,
        "run_date": started_at.astimezone(UTC).date(),
    }


def write_row(table: Table, row: dict) -> None:
    """Append one row, using whatever columns the table actually has.

    Projecting onto the live schema rather than assuming ARROW_SCHEMA is the
    second half of the migration safety net. If a column in SCHEMA has not
    reached this table yet, the row still lands without it. Losing one field
    of observability is recoverable; losing the row is not, and every job
    writes one of these in a finally block.
    """
    present = set(table.schema().column_names)
    projected = {k: v for k, v in row.items() if k in present}
    schema = pa.schema([f for f in ARROW_SCHEMA if f.name in present])
    table.append(pa.table({k: [v] for k, v in projected.items()}, schema=schema))
    log.info("run_log: %s %s %s", row["job"], row["run_id"], row["status"])
