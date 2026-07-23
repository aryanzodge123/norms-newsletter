"""Archival job and the gold permanent record (SPEC 6.9).

Runs after the deploy, as the last step of the publish workflow. It folds
the day's bronze and silver partitions into `gold` (Iceberg, compacted
Parquet, partitioned by month), stores the day's edition.json verbatim,
expires old snapshots, and drops today's bronze and silver partitions. Gold
is the permanent record and the writer stage's background retrieval source
(SPEC 6.5 stage 2).

Gold layout (proposed under SPEC 6.9, ratified in planning):

  gold.raw_items       bronze rows, month-partitioned
  gold.story_clusters  silver rows, month-partitioned
  gold.editions        one row per edition, edition.json verbatim

"Compacted" is concrete here: each day's rows are folded into their month
partition with a single overwrite, so a month is one data file rather than
one per day. That same overwrite is what makes the job idempotent, since it
is keyed by item_id / cluster_id / date and re-running a day merges the same
keys to the same result.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
from pyiceberg.catalog import Catalog
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import And, EqualTo, GreaterThanOrEqual, LessThan
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.table import Table
from pyiceberg.transforms import MonthTransform
from pyiceberg.types import DateType, IntegerType, NestedField, StringType

from . import bronze, runlog
from .config import REPO_ROOT, get_pipeline
from .silver import table as silver_table
from .storage import ensure_namespace, get_catalog

log = logging.getLogger("archive")

JOB = "archive"
NAMESPACE = "gold"

RAW_ITEMS = "gold.raw_items"
STORY_CLUSTERS = "gold.story_clusters"
EDITIONS = "gold.editions"

# Where the committed editions live on disk. The archival job reads today's
# from here to store it verbatim in gold.
EDITIONS_DIR = REPO_ROOT / "site" / "content" / "editions"

# gold.editions: one row per published edition. edition_json is the file
# verbatim (SPEC 6.9); edition_number and edition_type are pulled out as
# columns so gold can be queried without parsing every blob.
EDITIONS_SCHEMA = Schema(
    NestedField(1, "date", DateType(), required=True),
    NestedField(2, "edition_number", IntegerType(), required=True),
    NestedField(3, "edition_type", StringType(), required=True),
    NestedField(4, "edition_json", StringType(), required=True),
)
EDITIONS_ARROW = pa.schema(
    [
        pa.field("date", pa.date32(), nullable=False),
        pa.field("edition_number", pa.int32(), nullable=False),
        pa.field("edition_type", pa.string(), nullable=False),
        pa.field("edition_json", pa.string(), nullable=False),
    ]
)


def _month_partition(source_id: int) -> PartitionSpec:
    return PartitionSpec(
        PartitionField(
            source_id=source_id, field_id=1000, transform=MonthTransform(), name="month"
        )
    )


def ensure_raw_items(catalog: Catalog) -> Table:
    """gold.raw_items: bronze's schema, partitioned by month of ingest_date."""
    ensure_namespace(catalog, NAMESPACE)
    return catalog.create_table_if_not_exists(
        RAW_ITEMS, schema=bronze.SCHEMA, partition_spec=_month_partition(13)
    )


def ensure_story_clusters(catalog: Catalog) -> Table:
    """gold.story_clusters: silver's schema, partitioned by month of ingest_date."""
    ensure_namespace(catalog, NAMESPACE)
    return catalog.create_table_if_not_exists(
        STORY_CLUSTERS, schema=silver_table.SCHEMA, partition_spec=_month_partition(2)
    )


def ensure_editions(catalog: Catalog) -> Table:
    ensure_namespace(catalog, NAMESPACE)
    return catalog.create_table_if_not_exists(
        EDITIONS, schema=EDITIONS_SCHEMA, partition_spec=_month_partition(1)
    )


def _month_bounds(day: date) -> tuple[date, date]:
    """[first of this month, first of next month) for a month row-filter."""
    start = day.replace(day=1)
    nxt = date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
    return start, nxt


def _month_filter(date_col: str, day: date):
    start, nxt = _month_bounds(day)
    return And(GreaterThanOrEqual(date_col, start), LessThan(date_col, nxt))


def _dicts_to_arrow(rows: list[dict], schema: pa.Schema) -> pa.Table:
    columns: dict[str, list] = {name: [] for name in schema.names}
    for row in rows:
        for name in columns:
            columns[name].append(row[name])
    return pa.table(columns, schema=schema)


def _upsert_month(
    table: Table,
    *,
    date_col: str,
    key: tuple[str, ...],
    day: date,
    new_rows: list[dict],
    schema: pa.Schema,
) -> int:
    """Fold new_rows into their month partition and compact it to one file.

    Reads the whole month, merges the new rows in by key (new wins), and
    rewrites the month partition in a single overwrite. Two things fall out
    of doing it this way: the month becomes one data file (SPEC 6.9's
    "compacted"), and the job is idempotent because re-running a day merges
    the same keys back to the same rows.
    """
    if not new_rows:
        return 0

    month_filter = _month_filter(date_col, day)
    existing = table.scan(row_filter=month_filter).to_arrow().to_pylist()

    merged: dict[tuple, dict] = {}
    for row in existing:
        merged[tuple(row[col] for col in key)] = row
    added = 0
    for row in new_rows:
        k = tuple(row[col] for col in key)
        if k not in merged:
            added += 1
        merged[k] = row

    table.overwrite(
        _dicts_to_arrow(list(merged.values()), schema), overwrite_filter=month_filter
    )
    return added


def _expire_snapshots(table: Table, cutoff: datetime) -> None:
    """Expire snapshots older than cutoff (SPEC 6.9). Never fails the job.

    The current snapshot is a protected branch head and is always kept, so
    this only trims history that no longer needs to exist once the daily
    partitions it described are gone.
    """
    try:
        table.maintenance.expire_snapshots().older_than(cutoff).commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("snapshot expiry on %s failed, ignoring: %s", table.name(), exc)


def _load(catalog: Catalog, name: str) -> Table | None:
    try:
        return catalog.load_table(name)
    except NoSuchTableError:
        return None


# --- read helpers for the writer stage's background retrieval (SPEC 6.5) ---


def clusters_in_window(catalog: Catalog, start: date, end: date) -> list[dict]:
    """gold.story_clusters rows with start <= ingest_date < end.

    end is exclusive so today's own (not-yet-archived) clusters are never a
    candidate for its own prior mentions.
    """
    table = _load(catalog, STORY_CLUSTERS)
    if table is None:
        return []
    row_filter = And(GreaterThanOrEqual("ingest_date", start), LessThan("ingest_date", end))
    return table.scan(row_filter=row_filter).to_arrow().to_pylist()


def published_cluster_ids(catalog: Catalog, start: date, end: date) -> set[str]:
    """cluster_ids that actually appeared in an edition in [start, end).

    A prior mention is prior *coverage*, so a cluster that was scored but
    never published does not count. The edition JSON is the record of what
    was published, so this reads the cluster_ids out of it.

    Both placements count: a section card and a briefly line (SPEC 6.9,
    decision #23). A briefly line is thinner coverage than a card, but it is
    coverage, and a story the reader has already been shown is not new. This
    used to read section cards only, which under-reported what was published
    and let a briefly-only story come back the next day as if fresh.

    Briefly items published before that rule carry no cluster_id. They are
    skipped rather than treated as an error, so historical editions still
    load (SPEC 6.5).
    """
    table = _load(catalog, EDITIONS)
    if table is None:
        return set()
    row_filter = And(GreaterThanOrEqual("date", start), LessThan("date", end))
    published: set[str] = set()
    for row in table.scan(row_filter=row_filter).to_arrow().to_pylist():
        try:
            edition = json.loads(row["edition_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        for section in edition.get("sections", []) or []:
            for story in section.get("stories", []) or []:
                cid = story.get("cluster_id")
                if cid:
                    published.add(cid)
        for item in edition.get("briefly", []) or []:
            cid = item.get("cluster_id") if isinstance(item, dict) else None
            if cid:
                published.add(cid)
    return published


# --- the job ---


def _edition_row(path: Path, day: date) -> dict | None:
    if not path.exists():
        return None
    text = path.read_text()
    edition = json.loads(text)
    return {
        "date": day,
        "edition_number": int(edition["edition_number"]),
        "edition_type": edition["edition_type"],
        "edition_json": text,
    }


def archive_day(
    catalog: Catalog,
    ingest_date: date,
    *,
    now: datetime,
    editions_dir: Path = EDITIONS_DIR,
    snapshot_expiry_days: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Archive one day: bronze + silver + edition -> gold, then drop the day.

    Returns a small metrics dict. Safe to re-run: after the first pass the
    bronze and silver partitions are gone, so a second pass finds nothing to
    copy and the gold upserts are no-ops.
    """
    if snapshot_expiry_days is None:
        snapshot_expiry_days = get_pipeline().archive.snapshot_expiry_days

    bronze_table = bronze.ensure_table(catalog)
    silver_tbl = silver_table.ensure_table(catalog)

    bronze_items = bronze.read_partition(bronze_table, ingest_date)
    silver_rows = list(silver_table.read_partition(silver_tbl, ingest_date).values())
    edition_path = editions_dir / f"{ingest_date.isoformat()}.json"
    edition_row = _edition_row(edition_path, ingest_date)

    if dry_run:
        print(f"\narchive {ingest_date} (dry run, nothing written)")
        print(f"  bronze rows: {len(bronze_items)}")
        print(f"  silver clusters: {len(silver_rows)}")
        print(f"  edition.json: {'present' if edition_row else 'MISSING'}")
        return {
            "bronze": len(bronze_items),
            "silver": len(silver_rows),
            "edition": bool(edition_row),
        }

    gold_raw = ensure_raw_items(catalog)
    gold_clusters = ensure_story_clusters(catalog)
    gold_editions = ensure_editions(catalog)

    raw_written = _upsert_month(
        gold_raw,
        date_col="ingest_date",
        key=("item_id",),
        day=ingest_date,
        new_rows=[item.model_dump() for item in bronze_items],
        schema=bronze.ARROW_SCHEMA,
    )
    clusters_written = _upsert_month(
        gold_clusters,
        date_col="ingest_date",
        key=("cluster_id",),
        day=ingest_date,
        new_rows=silver_rows,
        schema=silver_table.ARROW_SCHEMA,
    )
    editions_written = _upsert_month(
        gold_editions,
        date_col="date",
        key=("date",),
        day=ingest_date,
        new_rows=[edition_row] if edition_row else [],
        schema=EDITIONS_ARROW,
    )

    cutoff = now - timedelta(days=snapshot_expiry_days)
    for table in (gold_raw, gold_clusters, gold_editions):
        _expire_snapshots(table, cutoff)

    # Drop the daily partitions: gold is now the record (SPEC 6.9). Done
    # last so a failure earlier leaves bronze/silver intact for a re-run.
    # Skipped when the partition is already empty, so an idempotent re-run
    # is a clean no-op rather than a no-match delete.
    if bronze_items:
        bronze_table.delete(EqualTo("ingest_date", ingest_date))
    if silver_rows:
        silver_tbl.delete(EqualTo("ingest_date", ingest_date))

    log.info(
        "archived %s: %d raw, %d clusters, %d edition; dropped daily partitions",
        ingest_date,
        raw_written,
        clusters_written,
        editions_written,
    )
    return {
        "bronze": len(bronze_items),
        "silver": len(silver_rows),
        "edition": bool(edition_row),
        "raw_written": raw_written,
        "clusters_written": clusters_written,
        "editions_written": editions_written,
        "edition_missing": edition_row is None,
    }


def run(target_date: date | None = None, *, dry_run: bool = False) -> int:
    run_id = runlog.make_run_id()
    started_at = datetime.now(UTC)
    ingest_date = target_date or started_at.date()

    catalog = get_catalog()
    status = "success"
    notes: list[str] = []
    metrics: dict = {}
    try:
        metrics = archive_day(catalog, ingest_date, now=started_at, dry_run=dry_run)
        if dry_run:
            return 0
        if metrics.get("edition_missing"):
            status = "partial"
            notes.append("no edition.json to archive for this date")
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        notes.append(f"archive failed: {type(exc).__name__}: {exc}")
        log.error(notes[-1])
    finally:
        if not dry_run:
            _log_run(run_id, started_at, status, metrics, "; ".join(notes) or None)

    return 1 if status == "failed" else 0


def _log_run(run_id, started_at, status, metrics, notes) -> None:
    try:
        items_in = metrics.get("bronze", 0) + metrics.get("silver", 0)
        items_out = (
            metrics.get("raw_written", 0)
            + metrics.get("clusters_written", 0)
            + metrics.get("editions_written", 0)
        )
        runlog.write_row(
            runlog.ensure_table(get_catalog()),
            runlog.build_row(
                run_id=run_id,
                job=JOB,
                started_at=started_at,
                ended_at=datetime.now(UTC),
                status=status,
                items_in=items_in,
                items_out=items_out,
                notes=notes,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        log.error("could not write run_log row: %s", exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Norm's Newsletter archival job (SPEC 6.9)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be archived, write nothing and drop nothing",
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        help="archive a past ingest_date, YYYY-MM-DD (default today)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    return run(args.date, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
