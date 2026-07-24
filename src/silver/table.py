"""silver.story_clusters (SPEC 6.4).

Follows the bronze table's shape. One difference that matters: bronze is
append-only, this table is rebuilt per partition. Each silver run
re-clusters the whole day and overwrites today's ingest_date partition, so
a missed or crashed cycle corrects itself on the next run rather than
leaving a permanent gap.

SPEC 6.4 calls this table the future eval dataset, which is why every row
carries model_version, prompt_version, and scored_at alongside the score.
A score without the thing that produced it is not evaluable.
"""

from __future__ import annotations

import logging
import time
from datetime import date

import pyarrow as pa
from pyiceberg.catalog import Catalog
from pyiceberg.exceptions import CommitFailedException
from pyiceberg.expressions import EqualTo
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.table import Table
from pyiceberg.transforms import IdentityTransform
from pyiceberg.types import (
    DateType,
    DoubleType,
    IntegerType,
    ListType,
    NestedField,
    StringType,
    TimestamptzType,
)

from .cluster import Cluster
from .score import ScoringResult
from ..storage import ensure_namespace

log = logging.getLogger(__name__)

NAMESPACE = "silver"
TABLE_NAME = "silver.story_clusters"

# Bounded reload-and-retry for the partition overwrite (SPEC 6.4, decision
# #30). The overwrite is a compare-and-swap against the snapshot the handle
# was loaded from, so a concurrent committer (the archival partition drop is
# the one other silver mutator, src/archive.py) can advance the table between
# ensure_table and the commit and lose us the race. Backoffs are the pauses
# between attempts, so len == OVERWRITE_MAX_ATTEMPTS - 1.
OVERWRITE_MAX_ATTEMPTS = 3
OVERWRITE_BACKOFFS_S = (0.5, 1.0)

SUMMARY_SEED_CHARS = 500

SCHEMA = Schema(
    NestedField(1, "cluster_id", StringType(), required=True),
    NestedField(2, "ingest_date", DateType(), required=True),
    NestedField(3, "topic", StringType(), required=False),
    NestedField(4, "headline", StringType(), required=True),
    NestedField(5, "summary_seed", StringType(), required=True),
    NestedField(
        6,
        "member_ids",
        ListType(element_id=20, element_type=StringType(), element_required=True),
        required=True,
    ),
    NestedField(7, "member_count", IntegerType(), required=True),
    NestedField(
        8,
        "sources",
        ListType(element_id=21, element_type=StringType(), element_required=True),
        required=True,
    ),
    NestedField(9, "score", IntegerType(), required=False),
    NestedField(10, "rationale", StringType(), required=False),
    NestedField(11, "confidence", DoubleType(), required=False),
    NestedField(12, "model_version", StringType(), required=True),
    NestedField(13, "prompt_version", StringType(), required=True),
    NestedField(14, "scored_at", TimestamptzType(), required=False),
)

PARTITION_SPEC = PartitionSpec(
    PartitionField(
        source_id=2, field_id=1000, transform=IdentityTransform(), name="ingest_date"
    )
)

ARROW_SCHEMA = pa.schema(
    [
        pa.field("cluster_id", pa.string(), nullable=False),
        pa.field("ingest_date", pa.date32(), nullable=False),
        pa.field("topic", pa.string(), nullable=True),
        pa.field("headline", pa.string(), nullable=False),
        pa.field("summary_seed", pa.string(), nullable=False),
        pa.field("member_ids", pa.list_(pa.field("element", pa.string(), nullable=False)), nullable=False),
        pa.field("member_count", pa.int32(), nullable=False),
        pa.field("sources", pa.list_(pa.field("element", pa.string(), nullable=False)), nullable=False),
        pa.field("score", pa.int32(), nullable=True),
        pa.field("rationale", pa.string(), nullable=True),
        pa.field("confidence", pa.float64(), nullable=True),
        pa.field("model_version", pa.string(), nullable=False),
        pa.field("prompt_version", pa.string(), nullable=False),
        pa.field("scored_at", pa.timestamp("us", tz="UTC"), nullable=True),
    ]
)


def ensure_table(catalog: Catalog) -> Table:
    ensure_namespace(catalog, NAMESPACE)
    return catalog.create_table_if_not_exists(
        TABLE_NAME, schema=SCHEMA, partition_spec=PARTITION_SPEC
    )


def build_row(cluster: Cluster, result: ScoringResult) -> dict:
    """One stored row. headline and summary_seed come from the cluster's
    seed member: deterministic code, never AI prose (rule zero)."""
    seed = cluster.seed
    return {
        "cluster_id": cluster.cluster_id,
        "ingest_date": seed.ingest_date,
        "topic": result.topic,
        "headline": seed.title,
        "summary_seed": seed.body_excerpt[:SUMMARY_SEED_CHARS].strip(),
        "member_ids": sorted(m.item_id for m in cluster.members),
        "member_count": len(cluster.members),
        "sources": sorted({m.source for m in cluster.members}),
        "score": result.score,
        "rationale": result.rationale,
        "confidence": result.confidence,
        "model_version": result.model_version,
        "prompt_version": result.prompt_version,
        "scored_at": result.scored_at,
    }


def to_arrow(rows: list[dict]) -> pa.Table:
    columns: dict[str, list] = {name: [] for name in ARROW_SCHEMA.names}
    for row in rows:
        for name in columns:
            columns[name].append(row[name])
    return pa.table(columns, schema=ARROW_SCHEMA)


def read_partition(table: Table, ingest_date: date) -> dict[str, dict]:
    """Stored rows for one day, keyed by cluster_id.

    Feeds the carry-forward in run_silver: decision #6 says re-score only
    new clusters and clusters whose member count changed, which means we
    have to know what the last run stored.
    """
    scan = table.scan(row_filter=EqualTo("ingest_date", ingest_date))
    return {row["cluster_id"]: row for row in scan.to_arrow().to_pylist()}


def overwrite_partition(table: Table, ingest_date: date, rows: list[dict]) -> int:
    """Replace one day's clusters wholesale.

    The rebuild is what makes a silver run idempotent: running it twice
    over the same bronze data leaves the same partition, and a run that
    was skipped earlier in the day is fully recovered by the next one.

    The overwrite is a compare-and-swap under Iceberg optimistic concurrency,
    against the snapshot this handle was loaded from in run_silver, minutes
    earlier and before a whole scoring pass. A concurrent committer that moved
    the table in between makes the commit raise CommitFailedException. This is
    what SPEC 6.2 already promises away ("overlapping runs are harmless"), true
    for append-only bronze but not, until here, for this overwrite. So a lost
    race reloads the handle and retries a bounded number of times (SPEC 6.4,
    decision #30) before the exception propagates to run_silver's write_failed
    path.

    A retry only needs fresh table metadata to commit rows that are already
    built from the clusters and scores: the stale partition read feeds only the
    carry-forward cost optimization, never correctness, so nothing is re-scored.
    The overwrite is a whole-partition replace, so last-writer-wins is the
    intended idempotent semantics and re-applying this deterministic rebuild is
    safe.
    """
    if not rows:
        log.info("silver: no clusters for %s, leaving partition untouched", ingest_date)
        return 0
    arrow_rows = to_arrow(rows)
    for attempt in range(1, OVERWRITE_MAX_ATTEMPTS + 1):
        try:
            table.overwrite(
                arrow_rows, overwrite_filter=EqualTo("ingest_date", ingest_date)
            )
            break
        except CommitFailedException:
            if attempt == OVERWRITE_MAX_ATTEMPTS:
                raise
            log.warning(
                "silver: overwrite for %s lost a commit race (attempt %d of %d), "
                "reloading and retrying",
                ingest_date,
                attempt,
                OVERWRITE_MAX_ATTEMPTS,
            )
            time.sleep(OVERWRITE_BACKOFFS_S[attempt - 1])
            table.refresh()
    log.info("silver: wrote %d clusters for %s", len(rows), ingest_date)
    return len(rows)
