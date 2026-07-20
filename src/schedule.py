"""DST-correct publish scheduling (SPEC 6.8, decision #7).

The publish workflow is triggered by two crons, `0 10 * * *` and
`0 11 * * *` (UTC). Exactly one of those two firings lands on 06:00 US
Eastern for any given date: 10:00 UTC while Eastern is on daylight time
(EDT, UTC-4) and 11:00 UTC while it is on standard time (EST, UTC-5). The
workflow calls `is_publish_time` at the top of the run and exits early
unless it returns True, so the edition is built once per day at 6am Eastern
without the workflow file having to know when the clocks change.

This is deterministic code with no network and no clock other than the one
passed in, which is what lets the DST behavior be pinned by tests
(CLAUDE.md rule 4).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

# The one moment each day the edition is built, in Eastern local time.
PUBLISH_HOUR = 6
PUBLISH_MINUTE = 0


def is_publish_time(now_utc: datetime) -> bool:
    """True only when `now_utc` is 06:00 US Eastern local time.

    `now_utc` must be timezone-aware. The two crons fire on the hour, so the
    minute check makes an off-schedule manual trigger at, say, 10:30 UTC a
    no-op rather than an accidental second edition. The wall-clock hour in
    Eastern is what matters, so the same code is correct on both sides of a
    DST transition and on the transition days themselves.
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    eastern = now_utc.astimezone(EASTERN)
    return eastern.hour == PUBLISH_HOUR and eastern.minute == PUBLISH_MINUTE
