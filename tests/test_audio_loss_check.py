"""The sustained audio loss check (SPEC section 8, decision #67).

It reads the recent `audio` run_log rows and exits non-zero only when the last
AUDIO_LOSS_THRESHOLD consecutive publishes all went out without audio. This is
the code behind the final publish-workflow step, so its exit code is the alert.

The distinction being tested is between a miss and a streak: one edition
without audio is correct behavior under SPEC 7 and must stay silent, while
three in a row is a broken feature and must not.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src import audio_loss_check, runlog

DAY = date(2026, 9, 14)


def _seed_audio_row(catalog, day: int, *, reasons, status="partial", hour=9, note=None):
    when = datetime(2026, 9, day, hour, 40, tzinfo=UTC)
    runlog.write_row(
        runlog.ensure_table(catalog),
        runlog.build_row(
            run_id=runlog.make_run_id(when),
            job="audio",
            started_at=when,
            ended_at=when,
            status=status,
            items_in=40,
            items_out=0 if reasons else 1,
            reasons=reasons,
            notes=note,
        ),
    )


def _missing(catalog, day: int, **kwargs):
    _seed_audio_row(catalog, day, reasons=["audio_missing"], **kwargs)


def _with_audio(catalog, day: int, **kwargs):
    _seed_audio_row(catalog, day, reasons=None, status="success", **kwargs)


@pytest.fixture
def wired(local_catalog, monkeypatch):
    monkeypatch.setattr(audio_loss_check, "get_catalog", lambda: local_catalog)
    monkeypatch.setattr(runlog, "get_catalog", lambda: local_catalog)
    return local_catalog


# --------------------------------------------------------------------------
# The threshold
# --------------------------------------------------------------------------
def test_the_threshold_is_three(wired):
    # The one number here that is a judgment call rather than a measurement.
    # Two would have fired on the ordinary rate (14 of 57 editions carried no
    # audio); three would have caught the 2026-09-09 to 2026-09-14 streak a day
    # before a person noticed it.
    assert audio_loss_check.AUDIO_LOSS_THRESHOLD == 3


def test_three_consecutive_misses_flag(wired):
    for day in (12, 13, 14):
        _missing(wired, day)
    assert audio_loss_check.run(DAY) == 1


def test_two_consecutive_misses_do_not_flag(wired):
    # A single miss, and even two, is what SPEC 7 promises. Staying quiet here
    # is the point: a signal that fires on correct behavior gets ignored.
    _with_audio(wired, 12)
    _missing(wired, 13)
    _missing(wired, 14)
    assert audio_loss_check.run(DAY) == 0


def test_a_success_in_the_middle_resets_the_streak(wired):
    # Five misses in six days is not the signal. Consecutive is, because a
    # recovered feature and a failing one have the same rate.
    for day in (9, 10):
        _missing(wired, day)
    _with_audio(wired, 11)
    for day in (12, 13):
        _missing(wired, day)
    assert audio_loss_check.run(DAY) == 0


def test_the_most_recent_run_is_what_counts(wired):
    # A long-past streak that has since recovered must not keep firing.
    for day in (9, 10, 11):
        _missing(wired, day)
    _with_audio(wired, 14)
    assert audio_loss_check.run(DAY) == 0


def test_a_re_run_that_recovered_the_audio_breaks_the_streak(wired):
    # A day can hold several audio rows. The last one by start time is what the
    # published edition actually ended up with, exactly as the degraded check
    # reads the last editor row.
    _missing(wired, 12)
    _missing(wired, 13)
    _missing(wired, 14, hour=9)
    _with_audio(wired, 14, hour=11)
    assert audio_loss_check.run(DAY) == 0


def test_a_fallback_day_ends_the_streak(wired):
    # A fallback edition carries no audio by design and run_audio deliberately
    # records no audio_missing code for it, so nothing was lost that day.
    _missing(wired, 12)
    _missing(wired, 13)
    _seed_audio_row(wired, 14, reasons=None, status="partial")
    assert audio_loss_check.run(DAY) == 0


def test_no_audio_rows_at_all_is_not_flagged(wired):
    # A day that never published is the healthcheck's concern, not this one.
    assert audio_loss_check.run(DAY) == 0


def test_future_rows_are_ignored(wired):
    # --date is for checking a past run_date, so rows after it must not count.
    for day in (12, 13, 14):
        _missing(wired, day)
    assert audio_loss_check.run(date(2026, 9, 13)) == 0


# --------------------------------------------------------------------------
# The streak counter itself, without a catalog
# --------------------------------------------------------------------------
def _row(reasons):
    return {"reasons": reasons, "run_date": DAY}


def test_streak_counts_from_the_front_only():
    rows = [_row('["audio_missing"]'), _row(None), _row('["audio_missing"]')]
    assert audio_loss_check.consecutive_audio_missing(rows) == 1


def test_streak_reads_other_reason_codes_as_a_break():
    rows = [_row('["audio_missing"]'), _row('["thin_grounding"]')]
    assert audio_loss_check.consecutive_audio_missing(rows) == 1


def test_streak_handles_a_row_carrying_several_codes():
    rows = [_row('["audio_missing", "thin_grounding"]'), _row('["audio_missing"]')]
    assert audio_loss_check.consecutive_audio_missing(rows) == 2


def test_streak_of_an_empty_history_is_zero():
    assert audio_loss_check.consecutive_audio_missing([]) == 0


# --------------------------------------------------------------------------
# The boundary with the degraded signal (decision #27 / #67)
# --------------------------------------------------------------------------
def test_audio_missing_is_not_a_degraded_reason():
    """The precision decision #27 exists to provide.

    "Degraded" means a fallback link-list published where a real edition was
    possible. A normal edition without audio is not that, so widening
    DEGRADED_REASONS to reuse its alert would cost the definition its meaning.
    This check is a second signal sharing a delivery mechanism, not a wider
    first one.
    """
    assert runlog.REASON_AUDIO_MISSING not in runlog.DEGRADED_REASONS
    assert runlog.is_degraded(["audio_missing"]) is False


def test_a_degraded_day_is_not_this_checks_business(wired):
    # A degraded editor row says nothing about audio. Only audio rows count.
    runlog.write_row(
        runlog.ensure_table(wired),
        runlog.build_row(
            run_id="x",
            job="editor",
            started_at=datetime(2026, 9, 14, 9, 30, tzinfo=UTC),
            ended_at=datetime(2026, 9, 14, 9, 35, tzinfo=UTC),
            status="partial",
            items_in=0,
            items_out=0,
            reasons=["assembly_fallback"],
        ),
    )
    assert audio_loss_check.run(DAY) == 0
