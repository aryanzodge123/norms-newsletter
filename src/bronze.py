"""bronze.raw_items: the append-only landing table (SPEC 6.3).

Append-only, partitioned by ingest_date, duplicate item_ids skipped.
Read only by silver jobs and the archival job.
"""

from __future__ import annotations

import logging
from datetime import date

import pyarrow as pa
from pyiceberg.catalog import Catalog
from pyiceberg.expressions import EqualTo, In
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.table import Table
from pyiceberg.transforms import IdentityTransform
from pyiceberg.types import (
    DateType,
    NestedField,
    StringType,
    TimestamptzType,
)

from .adapters.base import RawItem
from .storage import ensure_namespace

log = logging.getLogger(__name__)

NAMESPACE = "bronze"
TABLE_NAME = "bronze.raw_items"

SCHEMA = Schema(
    NestedField(1, "item_id", StringType(), required=True),
    NestedField(2, "source", StringType(), required=True),
    NestedField(3, "source_type", StringType(), required=True),
    NestedField(4, "topic_hint", StringType(), required=True),
    NestedField(5, "url", StringType(), required=True),
    NestedField(6, "canonical_url", StringType(), required=True),
    NestedField(7, "title", StringType(), required=True),
    NestedField(8, "body_excerpt", StringType(), required=True),
    NestedField(9, "author", StringType(), required=False),
    NestedField(10, "published_at", TimestamptzType(), required=True),
    NestedField(11, "fetched_at", TimestamptzType(), required=True),
    NestedField(12, "run_id", StringType(), required=True),
    NestedField(13, "ingest_date", DateType(), required=True),
)

PARTITION_SPEC = PartitionSpec(
    PartitionField(
        source_id=13, field_id=1000, transform=IdentityTransform(), name="ingest_date"
    )
)

ARROW_SCHEMA = pa.schema(
    [
        pa.field("item_id", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("source_type", pa.string(), nullable=False),
        pa.field("topic_hint", pa.string(), nullable=False),
        pa.field("url", pa.string(), nullable=False),
        pa.field("canonical_url", pa.string(), nullable=False),
        pa.field("title", pa.string(), nullable=False),
        pa.field("body_excerpt", pa.string(), nullable=False),
        pa.field("author", pa.string(), nullable=True),
        pa.field("published_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("fetched_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("run_id", pa.string(), nullable=False),
        pa.field("ingest_date", pa.date32(), nullable=False),
    ]
)


def ensure_table(catalog: Catalog) -> Table:
    ensure_namespace(catalog, NAMESPACE)
    return catalog.create_table_if_not_exists(
        TABLE_NAME, schema=SCHEMA, partition_spec=PARTITION_SPEC
    )


def to_arrow(items: list[RawItem]) -> pa.Table:
    columns: dict[str, list] = {name: [] for name in ARROW_SCHEMA.names}
    for item in items:
        row = item.model_dump()
        for name in columns:
            columns[name].append(row[name])
    return pa.table(columns, schema=ARROW_SCHEMA)


def existing_item_ids(table: Table, ingest_dates: set[date]) -> set[str]:
    """item_ids already stored in the partitions this batch touches."""
    if not ingest_dates:
        return set()
    scan = table.scan(
        row_filter=In("ingest_date", sorted(ingest_dates)),
        selected_fields=("item_id",),
    )
    return set(scan.to_arrow().column("item_id").to_pylist())


def read_partition(table: Table, ingest_date: date) -> list[RawItem]:
    """Every stored item for one ingest_date, for the silver stage.

    Silver re-reads the whole day on each run rather than tracking a
    watermark, which is what lets a missed cycle heal itself (SPEC 6.4).
    """
    scan = table.scan(row_filter=EqualTo("ingest_date", ingest_date))
    return [RawItem(**row) for row in scan.to_arrow().to_pylist()]


def append_items(table: Table, items: list[RawItem]) -> tuple[int, int]:
    """Append new rows, skipping duplicates. Returns (written, skipped).

    Idempotent by design (SPEC 6.2): running the collector twice over the
    same window writes nothing the second time. Deduplicates within the
    batch as well as against what is already stored, since two sources can
    surface the same canonical_url in one run.
    """
    if not items:
        return 0, 0

    seen: set[str] = set()
    batch: list[RawItem] = []
    duplicates = 0
    for item in items:
        if item.item_id in seen:
            duplicates += 1
            continue
        seen.add(item.item_id)
        batch.append(item)

    known = existing_item_ids(table, {item.ingest_date for item in batch})
    fresh = [item for item in batch if item.item_id not in known]
    duplicates += len(batch) - len(fresh)

    if fresh:
        table.append(to_arrow(fresh))

    log.info("bronze: wrote %d rows, skipped %d duplicates", len(fresh), duplicates)
    return len(fresh), duplicates
