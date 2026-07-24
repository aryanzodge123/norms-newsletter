"""Degraded-publication signal (SPEC section 8, decision #27).

The second of the two independent signals. healthchecks answers "did the site
publish"; this answers "was the published edition degraded", meaning a
fallback link-list went out when the day's data could have supported a real
edition (SPEC section 8's degraded reasons).

It runs as the last step of the publish workflow, after the deploy and the
healthchecks ping. It reads today's editor row from `ops.run_log` and exits
non-zero if that row is degraded, which reddens the GitHub Actions run and
sends its email. The site is already live and healthchecks is already green,
so this touches neither: it is an alert, not a failure of the publish.

Read-only. Writes no run_log row and makes no AI calls.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime

from . import runlog
from .storage import get_catalog

log = logging.getLogger("degraded_check")


def _todays_editor_row(catalog, target_date: date) -> dict | None:
    """The most recent editor row for the date, or None if there is none.

    A re-run day can hold several editor rows; the last one by start time is
    what actually shipped, so that is the one whose degraded-ness counts.
    """
    rows = [
        r
        for r in runlog.ensure_table(catalog).scan().to_arrow().to_pylist()
        if r["job"] == "editor" and r["run_date"] == target_date
    ]
    if not rows:
        return None
    return max(rows, key=lambda r: r["started_at"])


def run(target_date: date | None = None) -> int:
    ingest_date = target_date or datetime.now(UTC).date()
    row = _todays_editor_row(get_catalog(), ingest_date)

    if row is None:
        # No editor row is not this check's concern: a day that did not publish
        # is surfaced by the missing healthcheck, not by a degraded signal.
        log.info("no editor run_log row for %s; nothing to flag", ingest_date)
        return 0

    if runlog.is_degraded(row.get("reasons")):
        log.error(
            "DEGRADED publication for %s: editor run %s published a fallback "
            "when a real edition was possible (reasons=%s). Site is live and "
            "healthchecks is green; this reddens the Actions run as an alert.",
            ingest_date,
            row["run_id"],
            row.get("reasons"),
        )
        return 1

    log.info("publication for %s is not degraded", ingest_date)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Flag a degraded publication (SPEC section 8, decision #27)"
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        help="check a past run_date, YYYY-MM-DD (default today)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    return run(args.date)


if __name__ == "__main__":
    sys.exit(main())
