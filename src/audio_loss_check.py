"""Sustained audio loss signal (SPEC section 8, decision #67).

A third post-deploy signal, beside healthchecks ("did the site publish") and
the degraded check ("was the published edition a fallback when a real one was
possible"). This one answers "has the audio build stopped working".

One edition without audio is correct behavior: SPEC 7 contains a TTS failure
to "publish without an audio row", the audio step is continue-on-error so it
cannot redden a publish, and `audio_missing` is deliberately not a degraded
reason. That containment is also how the feature died quietly for four
consecutive days from 2026-09-11 to 2026-09-14: the run log recorded
`audio_missing` faithfully every morning and nothing read it back, so the
outage was found by a person noticing rather than by the system.

The distinction the system lacked is between a miss and a streak, so that is
what this measures: the most recent AUDIO_LOSS_THRESHOLD publish runs, all
carrying `audio_missing`. It reddens the Actions run after a successful
deploy, at the same volume as the degraded signal and by the same mechanism,
and it touches neither the published page nor healthchecks.

**This is not a widening of "degraded".** `audio_missing` stays out of
`DEGRADED_REASONS` (decision #27 gives that word the precise meaning of a
fallback link-list published where a real edition was possible, which a normal
edition without audio is not). It lives in its own module rather than inside
`degraded_check.py` for the same reason: two signals that share a delivery
mechanism, not one signal with a wider definition.

Read-only. Writes no run_log row and makes no AI calls.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime

from . import runlog
from .storage import get_catalog

log = logging.getLogger("audio_loss_check")

# How many consecutive audio runs must carry `audio_missing` before this
# fires. Three, because one miss is expected and two is still inside the
# ordinary rate: across the 57 editions published to 2026-09-14, 14 carried no
# audio, so a threshold of two would have fired on noise. Three would have
# fired on 2026-09-13, a day before the streak was noticed by hand, and is the
# lowest value the evidence supports rather than the lowest value that works.
# Consecutive runs rather than a rate over a window, because a rate cannot
# tell a recovered feature from a failing one.
AUDIO_LOSS_THRESHOLD = 3


def latest_audio_row_per_date(catalog, on_or_before: date) -> list[dict]:
    """One audio row per run_date, most recent date first.

    A re-run day holds several audio rows, and the last one by start time is
    what the published edition actually ended up with, exactly as the degraded
    check reads the last editor row. A re-run that recovers the audio must
    therefore break the streak, not extend it.
    """
    rows = [
        r
        for r in runlog.ensure_table(catalog).scan().to_arrow().to_pylist()
        if r["job"] == "audio" and r["run_date"] <= on_or_before
    ]
    by_date: dict[date, dict] = {}
    for row in rows:
        seen = by_date.get(row["run_date"])
        if seen is None or row["started_at"] > seen["started_at"]:
            by_date[row["run_date"]] = row
    return [by_date[day] for day in sorted(by_date, reverse=True)]


def consecutive_audio_missing(rows: list[dict]) -> int:
    """How many of the most recent rows carry `audio_missing`, unbroken.

    Counts from the front of a most-recent-first list and stops at the first
    row that does not, which is what makes this a streak rather than a rate.
    A day whose edition was a fallback carries no `audio_missing` (a fallback
    has no audio by design and run_audio deliberately records no code for it),
    so it ends the streak. That is correct: nothing was lost that day.
    """
    streak = 0
    for row in rows:
        if not runlog.has_reason(row.get("reasons"), runlog.REASON_AUDIO_MISSING):
            break
        streak += 1
    return streak


def run(target_date: date | None = None, *, threshold: int = AUDIO_LOSS_THRESHOLD) -> int:
    ingest_date = target_date or datetime.now(UTC).date()
    rows = latest_audio_row_per_date(get_catalog(), ingest_date)

    if not rows:
        # No audio row at all is not this check's concern. A day that did not
        # publish is surfaced by the missing healthcheck.
        log.info("no audio run_log rows on or before %s; nothing to flag", ingest_date)
        return 0

    streak = consecutive_audio_missing(rows)
    if streak >= threshold:
        log.error(
            "SUSTAINED AUDIO LOSS: the last %d publish runs (through %s) all "
            "published without audio. The site is live and healthchecks is "
            "green; this reddens the Actions run as an alert. Most recent "
            "audio notes: %s",
            streak,
            rows[0]["run_date"],
            "; ".join(
                f"{r['run_date']}: {r.get('notes') or 'no note'}"
                for r in rows[:threshold]
            ),
        )
        return 1

    log.info(
        "audio loss streak through %s is %d of %d; not flagging",
        rows[0]["run_date"],
        streak,
        threshold,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Flag sustained audio loss (SPEC section 8, decision #67)"
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        help="check as of a past run_date, YYYY-MM-DD (default today)",
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
