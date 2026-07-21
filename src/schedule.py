"""DST-correct, delay-tolerant publish scheduling (SPEC 6.8, decision #7).

The publish workflow is triggered by two crons, `30 9 * * *` and
`30 10 * * *` (UTC). Exactly one of those two firings lands on 05:30 US
Eastern for any given date: 09:30 UTC while Eastern is on daylight time
(EDT, UTC-4) and 10:30 UTC while it is on standard time (EST, UTC-5). That
05:30 Eastern moment is when the daily publish window opens.

The gate does not require the run to start at an exact minute. GitHub fires
scheduled crons late as a matter of course, and never early, so an
exact-instant check silently skips the day whenever a firing is delayed
(which is what happened on 2026-07-21). Instead `should_publish` proceeds
when two conditions hold: the Eastern wall clock is at or after the window
open for today, AND today's edition has not already been published. The
idempotency half, not the clock, is what enforces one edition per day, so a
late firing still publishes exactly once and a second firing (or a manual
re-trigger) is a harmless no-op.

The window opens at 05:30 Eastern rather than 06:00 to leave headroom for
GitHub's cron delay plus the roughly 5 to 9 minute build, so the site is live
by 06:00 Eastern.

This is deterministic code with no network and no clock other than the one
passed in, and the already-published flag is injected too, which is what lets
every case be pinned by tests (CLAUDE.md rule 4).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

# The moment each day the publish window opens, in Eastern local time.
WINDOW_OPEN_HOUR = 5
WINDOW_OPEN_MINUTE = 30


def window_is_open(now_utc: datetime) -> bool:
    """True when `now_utc` is at or after 05:30 US Eastern on its own date.

    The wall-clock time in Eastern is what matters, so the same code is
    correct on both sides of a DST transition and on the transition days
    themselves. A firing before the window (for example the 04:30 Eastern
    EST-side cron) returns False; any firing from 05:30 Eastern onward returns
    True, including a badly delayed one, because publishing late beats skipping
    the day.
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    eastern = now_utc.astimezone(EASTERN)
    return (eastern.hour, eastern.minute) >= (WINDOW_OPEN_HOUR, WINDOW_OPEN_MINUTE)


def should_publish(now_utc: datetime, *, already_published_today: bool) -> bool:
    """True when the publish should proceed: the window is open for today and
    today's edition has not already been committed.

    `already_published_today` is derived deterministically by the workflow from
    whether today's edition.json exists in site/content/editions/ (the
    publication record, decision #17). It is the idempotency guard that
    replaces the old exact-minute check: it stops a second edition regardless
    of how late or how many times the crons fire.
    """
    return window_is_open(now_utc) and not already_published_today
