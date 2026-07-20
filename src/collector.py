"""Collector entry point (SPEC 6.2).

Runs every enabled adapter, writes new rows to bronze, and records one
ops.run_log row. Fully idempotent: a second run over the same window
writes nothing.

One adapter failing never fails the run (SPEC 6.1). The run is `partial`
in that case, not `failed`.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
import time
from datetime import UTC, datetime, timedelta

from . import bronze, runlog
from .adapters.base import RawItem
from .config import SourceConfig, enabled_sources, get_pipeline
from .storage import get_catalog

log = logging.getLogger("collector")

JOB = "collector"


def resolve_adapter(source: SourceConfig):
    """Import the adapter class named in the registry (SPEC 6.1).

    Registry paths are written in the SPEC 6.1 form, relative to src/, so
    "adapters.hackernews.HackerNewsAdapter" resolves under this package.
    """
    module_path, _, class_name = source.adapter.rpartition(".")
    module = importlib.import_module(f"{__package__}.{module_path}")
    return getattr(module, class_name)


def run_adapter(
    source: SourceConfig, since: datetime, run_id: str, shortener_hosts: tuple[str, ...]
) -> tuple[list[RawItem], dict]:
    """Run one adapter. Returns its items and its health metrics."""
    started = time.monotonic()
    try:
        adapter_class = resolve_adapter(source)
        adapter = adapter_class(
            topic_hint=source.topic_hint,
            max_items=source.max_items_per_run,
            run_id=run_id,
            shortener_hosts=shortener_hosts,
        )
        items = adapter.fetch(since)
        latency_ms = int((time.monotonic() - started) * 1000)
        log.info("%s: %d items in %dms", source.name, len(items), latency_ms)
        return items, {"items": len(items), "errors": 0, "latency_ms": latency_ms}
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.monotonic() - started) * 1000)
        log.warning("%s failed, skipping: %s", source.name, exc)
        return [], {
            "items": 0,
            "errors": 1,
            "latency_ms": latency_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }


def collect(*, dry_run: bool = False) -> int:
    """One collection cycle. Returns the process exit code."""
    run_id = runlog.make_run_id()
    started_at = datetime.now(UTC)
    pipeline = get_pipeline()
    shortener_hosts = pipeline.canonical_url.shortener_hosts
    since = started_at - timedelta(hours=pipeline.collector.since_window_hours)

    sources = enabled_sources()
    log.info(
        "run %s: %d sources, since %s", run_id, len(sources), since.isoformat(timespec="seconds")
    )

    items: list[RawItem] = []
    metrics: dict[str, dict] = {}
    for source in sources:
        source_items, source_metrics = run_adapter(source, since, run_id, shortener_hosts)
        items.extend(source_items)
        metrics[source.name] = source_metrics

    failed_adapters = [name for name, m in metrics.items() if m["errors"]]

    if dry_run:
        print(f"\nrun_id {run_id} (dry run, nothing written)")
        for name, m in metrics.items():
            print(f"  {name:14} {m['items']:3d} items  {m['latency_ms']:5d}ms")
        print(f"  {'total':14} {len(items):3d} items")
        for item in items[:5]:
            print(f"\n  {item.item_id}  {item.published_at.isoformat(timespec='seconds')}")
            print(f"  {item.title[:78]}")
            print(f"  {item.canonical_url[:78]}")
        if failed_adapters:
            print(f"\n  adapters that failed: {', '.join(failed_adapters)}")
        return 0

    written = 0
    notes = None
    status = "partial" if failed_adapters else "success"
    try:
        catalog = get_catalog()
        table = bronze.ensure_table(catalog)
        written, skipped = bronze.append_items(table, items)
        if failed_adapters:
            notes = f"adapters failed: {', '.join(failed_adapters)}"
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        notes = f"bronze write failed: {type(exc).__name__}: {exc}"
        log.error(notes)
    finally:
        try:
            log_table = runlog.ensure_table(get_catalog())
            runlog.write_row(
                log_table,
                runlog.build_row(
                    run_id=run_id,
                    job=JOB,
                    started_at=started_at,
                    ended_at=datetime.now(UTC),
                    status=status,
                    items_in=len(items),
                    items_out=written,
                    adapter_metrics=metrics,
                    notes=notes,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            # The run itself already happened. A missing run_log row is
            # surfaced by the dead man's switch (SPEC section 8).
            log.error("could not write run_log row: %s", exc)

    return 1 if status == "failed" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Norm's Newsletter collector")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and normalize, print a summary, write nothing",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    return collect(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
