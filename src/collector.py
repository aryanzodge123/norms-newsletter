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

from . import bronze, enrich, health, runlog
from .adapters.base import RawItem
from .config import SourceConfig, enabled_sources, get_pipeline, get_settings
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
            name=source.name,
            topic_hint=source.topic_hint,
            max_items=source.max_items_per_run,
            run_id=run_id,
            shortener_hosts=shortener_hosts,
            feed_url=source.feed_url,
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


def collection_status(fetched_count: int, failed_adapters: list[str]) -> str:
    """The run_log status for a cycle, which also drives the healthcheck ping.

    A cycle that fetched nothing from any source is a blind collector (every
    source down or IP-blocked), not a healthy quiet window, so it fails and the
    cadence check fires (SPEC 8). This keys off items fetched, not items
    written: a healthy cycle legitimately writes 0 when everything is a
    duplicate. A bronze write failure is handled separately by the caller.
    """
    if fetched_count == 0:
        return "failed"
    return "partial" if failed_adapters else "success"


def collect(*, dry_run: bool = False) -> int:
    """One collection cycle. Returns the process exit code."""
    # Resolved inside the wrapper; kept out here so the final health ping can
    # fire after the wrapper has settled the status. None means "never got far
    # enough to ping", in which case the dead man's switch surfaces the stall.
    collect_url = None
    with runlog.logged_run(JOB, dry_run=dry_run) as rec:
        pipeline = get_pipeline()
        shortener_hosts = pipeline.canonical_url.shortener_hosts
        since = rec.started_at - timedelta(hours=pipeline.collector.since_window_hours)

        sources = enabled_sources()
        log.info(
            "run %s: %d sources, since %s",
            rec.run_id, len(sources), since.isoformat(timespec="seconds"),
        )

        items: list[RawItem] = []
        metrics: dict[str, dict] = {}
        for source in sources:
            source_items, source_metrics = run_adapter(source, since, rec.run_id, shortener_hosts)
            items.extend(source_items)
            metrics[source.name] = source_metrics

        failed_adapters = [name for name, m in metrics.items() if m["errors"]]
        # Measured before enrich (which preserves count): the true "collector is
        # blind" signal is what the sources returned, not what survives dedup.
        fetched_count = len(items)

        # SPEC 6.1 body_excerpt: adapters store the feed's summary, which is a
        # one-line blurb on most sources. Fetch the linked article so the text is
        # stored once, before bronze, and every later stage reads it: clustering
        # embeds real text, scoring stops being headline-only, and the writer
        # stage has something to ground on (decision #16). Never fatal: an item
        # whose fetch fails keeps its original excerpt.
        items, enrich_metrics = enrich.enrich_items(items, pipeline.enrich)
        metrics["_enrich"] = enrich_metrics
        rec.adapter_metrics = metrics
        rec.items_in = len(items)

        if dry_run:
            print(f"\nrun_id {rec.run_id} (dry run, nothing written)")
            for name, m in metrics.items():
                if name == "_enrich":
                    continue
                print(f"  {name:14} {m['items']:3d} items  {m['latency_ms']:5d}ms")
            print(f"  {'total':14} {len(items):3d} items")
            print(
                f"  {'enriched':14} {enrich_metrics['enriched']:3d} of "
                f"{enrich_metrics['fetched']} fetched (+{enrich_metrics['chars_added']} chars)"
            )
            grounded = sum(1 for i in items if len(i.body_excerpt.strip()) >= 400)
            print(f"  {'groundable':14} {grounded:3d} items at or above the 400-char floor")
            for item in items[:5]:
                print(f"\n  {item.item_id}  {item.published_at.isoformat(timespec='seconds')}")
                print(f"  {item.title[:78]}")
                print(f"  {item.canonical_url[:78]}")
            if failed_adapters:
                print(f"\n  adapters that failed: {', '.join(failed_adapters)}")
            return 0

        # The collector-cadence check (SPEC section 8). Its dead man's switch is
        # how a stalled or blind collector gets noticed; a failed ping never
        # fails the run.
        collect_url = get_settings().healthchecks_collect_url
        health.ping(collect_url, health.START)

        rec.status = collection_status(fetched_count, failed_adapters)
        if fetched_count == 0:
            rec.reason(runlog.REASON_NO_ITEMS)
            rec.note("no items fetched from any source")

        # Inner try so a bronze write failure keeps its specific note; the
        # outer wrapper would still catch it, but generically.
        try:
            catalog = get_catalog()
            table = bronze.ensure_table(catalog)
            written, _skipped = bronze.append_items(table, items)
            rec.items_out = written
            if failed_adapters and rec.status != "failed":
                rec.reason(runlog.REASON_ADAPTERS_FAILED)
                rec.note(f"adapters failed: {', '.join(failed_adapters)}")
        except Exception as exc:  # noqa: BLE001
            rec.status = "failed"
            rec.reason(runlog.REASON_WRITE_FAILED)
            rec.note(f"bronze write failed: {type(exc).__name__}: {exc}")
            log.error(rec.notes[-1])

    # After the wrapper: status is final, so the cadence check hears the truth.
    health.ping(collect_url, health.SUCCESS if rec.status != "failed" else health.FAIL)
    return 1 if rec.status == "failed" else 0


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
