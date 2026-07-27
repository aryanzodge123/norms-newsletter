"""Publish timeliness (SPEC section 8).

SPEC 6.8 opens the publish window at 05:30 ET so the site is live by 06:00 ET.
This is the measure that checks it, rather than leaving the claim asserted in
prose. A publication is *late* when the `site` job's `ended_at`, in Eastern
local time, falls after 06:00 on its own date.

Like degraded, late is a **derived query** over run_log and not a stored flag,
so it cannot drift from the data (decision #27). Nothing writes a "late"
column; this module computes it on read.

Unlike `degraded_check`, this is deliberately **not** wired into the publish
workflow and never exits non-zero for a late day. A late edition is complete,
just later than intended, so it carries no reason code and must not redden a
run. Section 8 puts it in the weekly 10-minute review, which is what this
module's `main` is for.

Sustained lateness is also the health signal for the external trigger
(SPEC 6.11). Because either scheduler alone publishes, a dead Worker or an
expired token fails nothing visible: it silently returns publication to
GitHub's cron timing, which ran 82 to 192 minutes late. A run of consecutive
late days is the only routine signal that says the dispatch path stopped
working, which is why the report prints the trigger beside each day.

Read-only. Writes no run_log row and makes no AI calls.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import runlog
from .storage import get_catalog

log = logging.getLogger("timeliness")

EASTERN = ZoneInfo("America/New_York")

# The moment each day by which the site should be live, in Eastern local time
# (SPEC 6.8). The window opens at 05:30; this is the deadline it exists to meet.
DEADLINE_HOUR = 6
DEADLINE_MINUTE = 0


def is_late(ended_at: datetime) -> bool:
    """True when a publish finishing at `ended_at` missed the 06:00 ET deadline.

    The Eastern wall clock is what matters, so this is correct on both sides of
    a DST change and on the transition days themselves, for the same reason
    `schedule.window_is_open` is. Exactly 06:00:00 is on time; the deadline is
    inclusive.
    """
    if ended_at.tzinfo is None:
        raise ValueError("ended_at must be timezone-aware")
    eastern = ended_at.astimezone(EASTERN)
    return (eastern.hour, eastern.minute, eastern.second) > (
        DEADLINE_HOUR,
        DEADLINE_MINUTE,
        0,
    )


@dataclass(frozen=True)
class DayResult:
    """One date's verdict. `late` is None when it could not be measured."""

    day: date
    late: bool | None
    ended_at_et: datetime | None
    trigger: str

    @property
    def verdict(self) -> str:
        if self.late is None:
            return "unknown"
        return "late" if self.late else "on time"


def _trigger_of(row: dict) -> str:
    """The `trigger=` note site_run writes, or 'unknown' if it is absent."""
    for part in (row.get("notes") or "").split(";"):
        part = part.strip()
        if part.startswith("trigger="):
            return part[len("trigger=") :] or "unknown"
    return "unknown"


def _site_rows_by_date(catalog) -> dict[date, dict]:
    """The last `site` row per run_date, by start time.

    A re-run day can hold several site rows; the last one is the publish that
    actually shipped, so its timing is the one that counts. Same rule
    `degraded_check` applies to editor rows.
    """
    rows = [
        r
        for r in runlog.ensure_table(catalog).scan().to_arrow().to_pylist()
        if r["job"] == "site"
    ]
    latest: dict[date, dict] = {}
    for row in rows:
        day = row["run_date"]
        if day not in latest or row["started_at"] > latest[day]["started_at"]:
            latest[day] = row
    return latest


def late_days(catalog, since: date, until: date | None = None) -> list[DayResult]:
    """Verdict per date from `since` to `until` inclusive (default: today).

    Every date in the range gets a row. A date with no `site` row reports
    `unknown` rather than on-time: the workflow step is continue-on-error, so a
    failed row write would otherwise be silently indistinguishable from a
    punctual publish, under-reporting lateness exactly when something is broken.
    """
    until = until or datetime.now(UTC).date()
    by_date = _site_rows_by_date(catalog)

    results = []
    day = since
    while day <= until:
        row = by_date.get(day)
        if row is None:
            results.append(DayResult(day, None, None, "unknown"))
        else:
            ended = row["ended_at"]
            if ended.tzinfo is None:
                ended = ended.replace(tzinfo=UTC)
            results.append(
                DayResult(day, is_late(ended), ended.astimezone(EASTERN), _trigger_of(row))
            )
        day += timedelta(days=1)
    return results


def format_report(results: list[DayResult]) -> str:
    """The weekly-review table (SPEC section 8)."""
    lines = ["date        verdict   live (ET)  trigger", "-" * 52]
    for r in results:
        live = r.ended_at_et.strftime("%H:%M:%S") if r.ended_at_et else "-"
        lines.append(f"{r.day}  {r.verdict:<9} {live:<10} {r.trigger}")

    measured = [r for r in results if r.late is not None]
    late = [r for r in measured if r.late]
    unknown = [r for r in results if r.late is None]
    lines.append("-" * 52)
    lines.append(
        f"{len(late)} late of {len(measured)} measured"
        + (f", {len(unknown)} unmeasured" if unknown else "")
    )
    return "\n".join(lines)


def run(since: date, until: date | None = None) -> int:
    print(format_report(late_days(get_catalog(), since, until)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish timeliness report (SPEC section 8)"
    )
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        required=True,
        help="first run_date to report, YYYY-MM-DD",
    )
    parser.add_argument(
        "--until",
        type=date.fromisoformat,
        help="last run_date to report, YYYY-MM-DD (default today)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    return run(args.since, args.until)


if __name__ == "__main__":
    sys.exit(main())
