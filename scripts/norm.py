"""Read-only operations helper for Norm's Newsletter.

A caretaker runs this to see whether the pipeline is healthy and to look at what
is in the tables, without writing any PyIceberg by hand. It is the tool the
RUNBOOK points at.

It is strictly READ-ONLY. It only ever scans tables and reads files on disk. It
never appends, overwrites, deletes, or calls an AI model, so running it can never
change the pipeline or cost money. It reuses the schemas and helpers already in
src/ rather than defining anything new.

Usage (from the repo root):

    uv run python scripts/norm.py status                # health snapshot (default)
    uv run python scripts/norm.py runlog --days 3       # recent job runs
    uv run python scripts/norm.py runlog --job collector
    uv run python scripts/norm.py table silver --date 2026-07-20
    uv run python scripts/norm.py cost --days 7         # AI spend per day

Reading the tables needs the R2 credentials in .env (the same ones the pipeline
uses). If they are missing, the script says so clearly instead of crashing.

The file is deliberately NOT named inspect.py: that would shadow Python's
standard-library `inspect` module, which PyIceberg imports.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Make `import src...` work however this script is launched (running a file puts
# scripts/ on the path, not the repo root).
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

EDITIONS_DIR = REPO_ROOT / "site" / "content" / "editions"

# The collector runs every 3 hours (SPEC 6.2). If the newest collector run is
# older than this, something on the mini PC is likely wrong.
COLLECTOR_STALE_HOURS = 4

# One row of the `table` command, per table: (table name, partition column,
# the columns worth printing).
TABLES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "bronze": ("bronze.raw_items", "ingest_date", ("item_id", "source", "title")),
    "silver": ("silver.story_clusters", "ingest_date", ("cluster_id", "topic", "score", "member_count", "headline")),
    "runlog": ("ops.run_log", "run_date", ("started_at", "job", "status", "ai_cost_estimate_usd", "notes")),
    "editions": ("gold.editions", "date", ("date", "edition_number", "edition_type")),
}


# --------------------------------------------------------------------------- #
# Catalog / table access (read-only)
# --------------------------------------------------------------------------- #

def _catalog():
    """Connect to the R2 Iceberg catalog, or exit with a clear message."""
    try:
        from src.storage import get_catalog

        return get_catalog()
    except Exception as exc:  # noqa: BLE001 - a caretaker wants a message, not a traceback
        print(f"Could not connect to the R2 catalog: {exc}", file=sys.stderr)
        print(
            "Check that .env has R2_CATALOG_URI, R2_WAREHOUSE, and R2_TOKEN "
            "(see SETUP.md and RUNBOOK.md).",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _load(catalog, name: str):
    """Load a table, or return None if it does not exist yet. Never creates."""
    from pyiceberg.exceptions import NoSuchTableError

    try:
        return catalog.load_table(name)
    except NoSuchTableError:
        return None


def _runlog_rows(catalog, days: int, job: str | None = None) -> list[dict] | None:
    """ops.run_log rows from the last `days` days, newest first. None if no table."""
    table = _load(catalog, "ops.run_log")
    if table is None:
        return None
    from pyiceberg.expressions import GreaterThanOrEqual

    start = datetime.now(UTC).date() - timedelta(days=days)
    rows = table.scan(row_filter=GreaterThanOrEqual("run_date", start)).to_arrow().to_pylist()
    if job:
        rows = [r for r in rows if r["job"] == job]
    rows.sort(key=lambda r: r["started_at"], reverse=True)
    return rows


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #

def _ts(value) -> str:
    """A timestamp as a short, readable UTC string."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M")
    return str(value)


def _age(value) -> str:
    """How long ago a timestamp was, e.g. '2h 5m ago'."""
    if not isinstance(value, datetime):
        return "?"
    delta = datetime.now(UTC) - value.astimezone(UTC)
    minutes = int(delta.total_seconds() // 60)
    if minutes < 0:
        return "just now"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m ago" if hours else f"{minutes}m ago"


def _cost(value) -> str:
    return f"${value:.4f}" if isinstance(value, (int, float)) else "-"


def _print_runlog_row(row: dict) -> None:
    mark = " " if row["status"] == "success" else "!"
    line = (
        f" {mark} {_ts(row['started_at'])}  {row['job']:<9} {row['status']:<8}"
        f" in={row['items_in']:<4} out={row['items_out']:<4} {_cost(row.get('ai_cost_estimate_usd'))}"
    )
    print(line)
    if row.get("notes"):
        print(f"      notes: {row['notes']}")


# --------------------------------------------------------------------------- #
# Editions on disk
# --------------------------------------------------------------------------- #

def _latest_edition() -> dict | None:
    """The newest committed edition.json on disk. Filenames are dates, so a
    plain sort is chronological."""
    if not EDITIONS_DIR.is_dir():
        return None
    files = sorted(EDITIONS_DIR.glob("*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text())


def _edition_summary(edition: dict) -> str:
    etype = edition.get("edition_type")
    number = edition.get("edition_number")
    if etype == "fallback":
        stories = len(edition.get("stories", []))
        return f"No. {number}  {edition['date']}  {etype}  ({stories} ranked stories, no audio)"
    stories = sum(len(s.get("stories", [])) for s in edition.get("sections", []))
    audio = "audio present" if edition.get("audio") else "no audio"
    return f"No. {number}  {edition['date']}  {etype}  ({stories} stories, {audio})"


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_status(args) -> int:
    """A one-screen health snapshot: latest edition + recent runs + freshness."""
    print("Norm's Newsletter status\n" + "=" * 40)

    edition = _latest_edition()
    print("\nLatest edition on disk (site/content/editions/):")
    print("  " + (_edition_summary(edition) if edition else "none found"))
    if edition:
        today = datetime.now(UTC).date().isoformat()
        if edition["date"] != today:
            print(f"  NOTE: newest edition is {edition['date']}, not today ({today} UTC).")

    catalog = _catalog()
    rows = _runlog_rows(catalog, days=2)
    if rows is None:
        print("\nops.run_log does not exist yet (no job has ever run).")
        return 0
    if not rows:
        print("\nNo job runs recorded in the last 2 days. The pipeline looks idle.")
        return 0

    # Freshness: newest run of each job, and a warning if the collector is stale.
    newest: dict[str, dict] = {}
    for row in rows:
        newest.setdefault(row["job"], row)  # rows are newest-first

    print("\nMost recent run of each job:")
    for job in ("collector", "silver", "editor", "audio", "archive"):
        row = newest.get(job)
        if row is None:
            print(f"  {job:<9} none in the last 2 days")
            continue
        print(f"  {job:<9} {row['status']:<8} {_age(row['started_at'])}  {_cost(row.get('ai_cost_estimate_usd'))}")

    collector = newest.get("collector")
    if collector is not None and isinstance(collector["started_at"], datetime):
        stale = datetime.now(UTC) - collector["started_at"].astimezone(UTC) > timedelta(hours=COLLECTOR_STALE_HOURS)
        if stale:
            print(
                f"\n  WARNING: newest collector run is {_age(collector['started_at'])}, "
                f"over {COLLECTOR_STALE_HOURS}h. Check the mini PC (RUNBOOK: 'Collector stopped')."
            )

    bad = [r for r in rows if r["status"] != "success"]
    if bad:
        print(f"\nNon-success runs in the last 2 days ({len(bad)}):")
        for row in bad:
            _print_runlog_row(row)
    else:
        print("\nAll runs in the last 2 days succeeded.")
    return 0


def cmd_runlog(args) -> int:
    """Recent job runs, newest first."""
    catalog = _catalog()
    rows = _runlog_rows(catalog, days=args.days, job=args.job)
    if rows is None:
        print("ops.run_log does not exist yet (no job has ever run).")
        return 0
    scope = f"job={args.job}" if args.job else "all jobs"
    print(f"ops.run_log, last {args.days} day(s), {scope}: {len(rows)} run(s)\n")
    for row in rows:
        _print_runlog_row(row)
    return 0


def cmd_table(args) -> int:
    """Count and peek rows in one table for a day."""
    name, part_col, fields = TABLES[args.table]
    catalog = _catalog()
    table = _load(catalog, name)
    if table is None:
        print(f"{name} does not exist yet.")
        return 0

    scan = table.scan()
    if args.date:
        from pyiceberg.expressions import EqualTo

        try:
            day = date.fromisoformat(args.date)
        except ValueError:
            print(f"--date must be YYYY-MM-DD, got {args.date!r}", file=sys.stderr)
            return 2
        scan = table.scan(row_filter=EqualTo(part_col, day))

    rows = scan.to_arrow().to_pylist()
    where = f" for {part_col}={args.date}" if args.date else ""
    print(f"{name}{where}: {len(rows)} row(s). Showing up to {args.limit}:\n")
    for row in rows[: args.limit]:
        parts = []
        for field in fields:
            value = row.get(field)
            if isinstance(value, datetime):
                value = _ts(value)
            elif isinstance(value, str) and len(value) > 60:
                value = value[:57] + "..."
            parts.append(f"{field}={value}")
        print("  " + "  ".join(parts))
    return 0


def cmd_cost(args) -> int:
    """AI spend per day from ops.run_log, to watch the under-$25/month budget."""
    catalog = _catalog()
    rows = _runlog_rows(catalog, days=args.days)
    if rows is None:
        print("ops.run_log does not exist yet (no job has ever run).")
        return 0

    by_day: dict[date, float] = {}
    for row in rows:
        cost = row.get("ai_cost_estimate_usd")
        if isinstance(cost, (int, float)):
            by_day[row["run_date"]] = by_day.get(row["run_date"], 0.0) + cost

    if not by_day:
        print(f"No AI cost recorded in the last {args.days} day(s).")
        return 0

    print(f"Estimated AI cost per day, last {args.days} day(s):\n")
    total = 0.0
    for day in sorted(by_day):
        print(f"  {day.isoformat()}  ${by_day[day]:.4f}")
        total += by_day[day]
    days = max(len(by_day), 1)
    print(f"\n  total ${total:.4f} over {days} day(s), avg ${total / days:.4f}/day")
    print(f"  projected ~${total / days * 30:.2f}/month (budget is under $25, SPEC 9)")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only status and table inspector for Norm's Newsletter.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    p_status = sub.add_parser("status", help="health snapshot (default)")
    p_status.set_defaults(func=cmd_status)

    p_runlog = sub.add_parser("runlog", help="recent job runs")
    p_runlog.add_argument("--days", type=int, default=2, help="how many days back (default 2)")
    p_runlog.add_argument("--job", help="filter to one job (collector, silver, editor, audio, archive)")
    p_runlog.set_defaults(func=cmd_runlog)

    p_table = sub.add_parser("table", help="count and peek rows in a table")
    p_table.add_argument("table", choices=sorted(TABLES), help="which table")
    p_table.add_argument("--date", help="a single day, YYYY-MM-DD")
    p_table.add_argument("--limit", type=int, default=10, help="max rows to print (default 10)")
    p_table.set_defaults(func=cmd_table)

    p_cost = sub.add_parser("cost", help="AI spend per day")
    p_cost.add_argument("--days", type=int, default=7, help="how many days back (default 7)")
    p_cost.set_defaults(func=cmd_cost)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        # No subcommand means the default health snapshot.
        return cmd_status(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
