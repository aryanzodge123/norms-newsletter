"""Whole-year simulation of every publish trigger (SPEC 6.11, 6.8, decision #31).

The individual gate rules are pinned in test_schedule.py. This is the other
question: when all five daily triggers are replayed against the real gate, for
every date across two years, does the system publish exactly once a day and
does it beat the 06:00 ET deadline?

That is worth simulating rather than spot-checking because the answer depends
on DST, and the interesting dates are the two transition days plus whatever is
adjacent to them. A year of dates covers every case without anyone guessing
which ones matter.

**GitHub's crons are simulated late, because they are.** Measured 2026-07-21 to
2026-07-27, the publish crons were created 82 to 192 minutes after target on
every single day (decision #31). Simulating them as punctual would model a
system that does not exist, and would make these tests agree with a design
that fails in production. `CRON_DELAY` is the observed floor, not a guess.

Cheap and fully deterministic: `should_publish` takes both its clock and its
already-published flag as arguments, so no clock is mocked and no IO happens.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.schedule import should_publish
from src.timeliness import is_late

EASTERN = ZoneInfo("America/New_York")

# SPEC 6.8. Nominal times; GitHub delivers these late (see CRON_DELAY).
CRONS = ((9, 30), (10, 30))

# SPEC 6.11. Cloudflare, 5 minutes after the window opens, plus one retry.
WORKER_FIRINGS = ((9, 35), (10, 35), (11, 35))

# The best cron delay observed across seven days. The worst was 192 minutes.
# Using the floor makes these tests the conservative case: if the design holds
# at 82 minutes it holds at 192.
CRON_DELAY = timedelta(minutes=82)


def _triggers(day: date, *, cron_delay: timedelta = CRON_DELAY):
    """Every firing for one morning, in the order it actually arrives."""
    fired = [
        (datetime(day.year, day.month, day.day, h, m, tzinfo=UTC) + cron_delay, "cron")
        for h, m in CRONS
    ] + [
        (datetime(day.year, day.month, day.day, h, m, tzinfo=UTC), "worker")
        for h, m in WORKER_FIRINGS
    ]
    return sorted(fired)


def _simulate(day: date, *, cron_delay: timedelta = CRON_DELAY):
    """Replay one morning. Returns (kind, utc time) of the firing that published.

    Mirrors production: each firing checks the gate, and the first one that
    proceeds commits the edition, which flips `already_published` for the rest.
    """
    already = False
    for now, kind in _triggers(day, cron_delay=cron_delay):
        if should_publish(now, already_published_today=already):
            already = True
            return kind, now
    return None


def _dates(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


ALL_DAYS = list(_dates(date(2026, 1, 1), date(2027, 12, 31)))


def test_every_day_publishes_exactly_once():
    """No date is skipped and no date publishes twice.

    Skipping is the 2026-07-21 failure decision #7 was written for. Double
    publishing is what the idempotency half of the gate prevents, and it is the
    risk adding a third trigger could have introduced.
    """
    missed = [d for d in ALL_DAYS if _simulate(d) is None]
    assert not missed, f"{len(missed)} day(s) never published, first {missed[:3]}"


def test_every_day_is_live_before_the_deadline():
    """The whole point of SPEC 6.11: publication beats 06:00 ET every day."""
    for day in ALL_DAYS:
        _, fired_at = _simulate(day)
        assert not is_late(fired_at), (
            f"{day}: publish fired at {fired_at.astimezone(EASTERN):%H:%M %Z}, "
            "after the deadline"
        )


def test_the_worker_publishes_every_day_given_observed_cron_delay():
    """With GitHub as late as it really is, the Worker is what publishes.

    This is the design claim, and it is worth stating as a test because it is
    conditional: given *punctual* crons the 09:30 firing would win by five
    minutes (see the test below). The Worker matters precisely because that
    punctual world is not the one this project runs in.
    """
    kinds = {_simulate(day)[0] for day in ALL_DAYS}
    assert kinds == {"worker"}


def test_a_punctual_cron_would_have_been_fine_on_its_own():
    """The counterfactual, kept honest.

    If GitHub fired its crons on time, the 09:30/10:30 firing would land exactly
    at 05:30 ET and beat the deadline without any Worker at all. SPEC 6.11
    exists because of GitHub's delivery, not because the cron schedule was ever
    wrong. If GitHub's punctuality is ever fixed, this test is the evidence that
    the Worker could be retired rather than debugged.
    """
    for day in ALL_DAYS[:120]:
        kind, fired_at = _simulate(day, cron_delay=timedelta(0))
        assert kind == "cron"
        assert not is_late(fired_at)
        assert fired_at.astimezone(EASTERN).strftime("%H:%M") == "05:30"


def _cron_only_publish(day: date, delay: timedelta) -> datetime:
    """When the day would publish with GitHub's crons alone, at a given delay."""
    for now, kind in _triggers(day, cron_delay=delay):
        if kind == "cron" and should_publish(now, already_published_today=False):
            return now
    raise AssertionError(f"{day}: cron-only never published")


def test_without_the_worker_every_edt_day_is_late():
    """The problem statement, as a test.

    Crons only, at their observed *best* delay of 82 minutes: every day on
    daylight time misses 06:00 ET. All seven measured days were July, so this
    is the baseline SPEC section 8 records and what the milestone has to beat.
    """
    edt = [d for d in ALL_DAYS if _cron_only_publish(d, CRON_DELAY).astimezone(EASTERN).dst()]
    assert len(edt) > 400, "expected most of two years to be on daylight time"
    for day in edt:
        assert is_late(_cron_only_publish(day, CRON_DELAY))


def test_on_standard_time_a_best_case_cron_scrapes_in():
    """The precise limit of the above, worth pinning so nobody over-claims it.

    During EST the 09:30 UTC cron is 04:30 Eastern, before the window, so an
    82-minute delay pushes it to 05:52 Eastern: inside the window and just
    ahead of the deadline. GitHub's lateness is accidentally load-bearing
    there. It does not rescue the design, as the next test shows, but "every
    day is late without the Worker" would be false as a blanket claim and this
    records why.
    """
    winter = date(2026, 1, 1)
    fired = _cron_only_publish(winter, CRON_DELAY)
    assert fired.astimezone(EASTERN).strftime("%H:%M") == "05:52"
    assert not is_late(fired)


def test_at_the_observed_worst_delay_every_day_is_late_without_the_worker():
    """192 minutes, the worst delay measured (2026-07-27). No season survives it.

    This is the case that matters, because the delay is unbounded and not
    tunable: the design cannot rely on GitHub happening to land in the window.
    """
    worst = timedelta(minutes=192)
    for day in ALL_DAYS:
        assert is_late(_cron_only_publish(day, worst)), f"{day}: somehow on time"


def test_publishing_trigger_is_never_before_the_window():
    for day in ALL_DAYS:
        _, fired_at = _simulate(day)
        eastern = fired_at.astimezone(EASTERN)
        assert (eastern.hour, eastern.minute) >= (5, 30), f"{day}: fired before 05:30 ET"


# ---------------------------------------------------------------------------
# The dates that actually decide the above
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "day,expected_utc_hour",
    [
        (date(2026, 3, 7), 10),  # day before spring forward, still EST
        (date(2026, 3, 8), 9),  # spring forward, now EDT
        (date(2026, 3, 9), 9),  # day after
        (date(2026, 10, 31), 9),  # day before fall back, still EDT
        (date(2026, 11, 1), 10),  # fall back, now EST
        (date(2026, 11, 2), 10),  # day after
        (date(2028, 2, 29), 10),  # leap day, EST
    ],
)
def test_dst_boundaries_pick_the_right_worker_firing(day, expected_utc_hour):
    """Exactly one of the 09:35 / 10:35 pair is 05:35 Eastern, whatever the season."""
    kind, fired_at = _simulate(day)
    assert kind == "worker"
    assert (fired_at.hour, fired_at.minute) == (expected_utc_hour, 35)
    assert fired_at.astimezone(EASTERN).strftime("%H:%M") == "05:35"


# ---------------------------------------------------------------------------
# Regression: the real 2026-07-27 sequence
# ---------------------------------------------------------------------------
def test_the_2026_07_27_late_crons_are_noops():
    """The day that prompted SPEC 6.11.

    A manual dispatch published at 12:21Z, then GitHub's crons finally arrived
    at 12:42Z and 13:23Z, 192 and 173 minutes after target. Both correctly
    skipped. That is the evidence a third trigger is safe to add, so it is worth
    keeping as a test and not only in the decision log.
    """
    for hour, minute in ((12, 42), (13, 23)):
        late = datetime(2026, 7, 27, hour, minute, tzinfo=UTC)
        assert should_publish(late, already_published_today=True) is False
        # ... and the window itself was wide open; only idempotency stopped them.
        assert should_publish(late, already_published_today=False) is True


def test_a_late_cron_still_rescues_a_day_the_worker_missed():
    """If the Worker dies, GitHub's crons must still publish (SPEC 7).

    This is the failure mode section 8's timeliness measure watches for: the day
    is saved, but late, and nothing else says so.
    """
    worker_dead_but_cron_arrives = datetime(2026, 7, 28, 11, 30, tzinfo=UTC)
    assert should_publish(worker_dead_but_cron_arrives, already_published_today=False)
    assert is_late(worker_dead_but_cron_arrives) is True
