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
    return catalog.create_table_if_not_exists(
        TABLE_NAME, schema=SCHEMA, partition_spec=PARTITION_SPEC
    )


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
        "notes": notes,
        "run_date": started_at.astimezone(UTC).date(),
    }


def write_row(table: Table, row: dict) -> None:
    table.append(pa.table({k: [v] for k, v in row.items()}, schema=ARROW_SCHEMA))
    log.info("run_log: %s %s %s", row["job"], row["run_id"], row["status"])
