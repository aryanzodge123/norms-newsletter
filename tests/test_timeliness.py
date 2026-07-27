"""The publish timeliness measure (SPEC section 8).

Late is a derived query over run_log, not a stored flag (decision #27), so
these tests pin two things: the 06:00 Eastern boundary itself, and the read
path that turns `site` rows into a verdict per day.

The read path's sharp edge is the unmeasured day. The workflow step that writes
the `site` row is continue-on-error, so a day with no row must report `unknown`
and never `on time`. Getting that wrong would under-report lateness exactly
when something else is already broken.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src import runlog, timeliness

EASTERN = ZoneInfo("America/New_York")


def _et(y, m, d, hour, minute=0, second=0) -> datetime:
    return datetime(y, m, d, hour, minute, second, tzinfo=EASTERN)


def _seed_site_row(catalog, *, ended_at, started_at=None, trigger="worker"):
    started = started_at or ended_at - timedelta(minutes=9)
    runlog.write_row(
        runlog.ensure_table(catalog),
        runlog.build_row(
            run_id=runlog.make_run_id(started),
            job="site",
            started_at=started,
            ended_at=ended_at,
            status="success",
            items_in=1,
            items_out=17,
            notes=f"trigger={trigger}; edition_type=normal",
        ),
    )


@pytest.fixture
def wired(local_catalog, monkeypatch):
    monkeypatch.setattr(timeliness, "get_catalog", lambda: local_catalog)
    monkeypatch.setattr(runlog, "get_catalog", lambda: local_catalog)
    return local_catalog


# ---------------------------------------------------------------------------
# is_late: the 06:00 Eastern boundary
# ---------------------------------------------------------------------------
def test_before_six_is_on_time():
    assert timeliness.is_late(_et(2026, 7, 20, 5, 45)) is False


def test_exactly_six_is_on_time():
    # The deadline is inclusive: 06:00:00 met it.
    assert timeliness.is_late(_et(2026, 7, 20, 6, 0, 0)) is False


def test_one_second_past_six_is_late():
    assert timeliness.is_late(_et(2026, 7, 20, 6, 0, 1)) is True


def test_the_observed_baseline_is_late():
    # The 2026-07-21 to 07-27 range landed 07:15 to 08:52 ET. If the measure
    # ever calls these on time, it is wrong (SPEC section 8's baseline).
    for hour, minute in ((7, 15), (8, 52)):
        assert timeliness.is_late(_et(2026, 7, 24, hour, minute)) is True


def test_boundary_holds_on_both_sides_of_dst():
    # Eastern wall clock is what matters, so the same local time is the same
    # verdict in both seasons, exactly as schedule.window_is_open behaves.
    assert timeliness.is_late(_et(2026, 1, 20, 5, 59)) is False
    assert timeliness.is_late(_et(2026, 1, 20, 6, 1)) is True
    assert timeliness.is_late(_et(2026, 7, 20, 5, 59)) is False
    assert timeliness.is_late(_et(2026, 7, 20, 6, 1)) is True


def test_utc_input_is_converted_not_compared_raw():
    # 10:30 UTC is 05:30 EST (on time) in January and 06:30 EDT (late) in July.
    # Same UTC clock time, opposite verdicts: proof the conversion happens.
    assert timeliness.is_late(datetime(2026, 1, 20, 10, 30, tzinfo=UTC)) is False
    assert timeliness.is_late(datetime(2026, 7, 20, 10, 30, tzinfo=UTC)) is True


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        timeliness.is_late(datetime(2026, 7, 20, 5, 45))


# ---------------------------------------------------------------------------
# late_days: the read path
# ---------------------------------------------------------------------------
def test_on_time_day_reads_back_on_time(wired):
    _seed_site_row(wired, ended_at=_et(2026, 7, 20, 5, 44))
    (result,) = timeliness.late_days(wired, date(2026, 7, 20), date(2026, 7, 20))
    assert result.late is False
    assert result.verdict == "on time"
    assert result.trigger == "worker"


def test_late_day_reads_back_late(wired):
    _seed_site_row(wired, ended_at=_et(2026, 7, 20, 8, 52), trigger="schedule")
    (result,) = timeliness.late_days(wired, date(2026, 7, 20), date(2026, 7, 20))
    assert result.late is True
    assert result.trigger == "schedule"


def test_a_day_with_no_site_row_is_unknown_not_on_time(wired):
    """The sharp edge. A failed row write must never read as a punctual day."""
    (result,) = timeliness.late_days(wired, date(2026, 7, 20), date(2026, 7, 20))
    assert result.late is None
    assert result.verdict == "unknown"
    assert result.trigger == "unknown"


def test_gaps_inside_a_range_are_reported_not_skipped(wired):
    _seed_site_row(wired, ended_at=_et(2026, 7, 20, 5, 44))
    _seed_site_row(wired, ended_at=_et(2026, 7, 22, 5, 44))
    results = timeliness.late_days(wired, date(2026, 7, 20), date(2026, 7, 22))
    assert [r.verdict for r in results] == ["on time", "unknown", "on time"]


def test_a_rerun_day_uses_the_last_row(wired):
    """Several site rows in a day: the one that shipped is the last one."""
    early = _et(2026, 7, 20, 5, 40)
    late = _et(2026, 7, 20, 9, 30)
    _seed_site_row(wired, started_at=early - timedelta(minutes=9), ended_at=early)
    _seed_site_row(wired, started_at=late - timedelta(minutes=9), ended_at=late)
    (result,) = timeliness.late_days(wired, date(2026, 7, 20), date(2026, 7, 20))
    assert result.late is True


def test_other_jobs_are_ignored(wired):
    """Only the site row measures publication. An editor row must not count."""
    now = _et(2026, 7, 20, 5, 44)
    runlog.write_row(
        runlog.ensure_table(wired),
        runlog.build_row(
            run_id=runlog.make_run_id(now), job="editor",
            started_at=now, ended_at=now, status="success",
            items_in=1, items_out=1,
        ),
    )
    (result,) = timeliness.late_days(wired, date(2026, 7, 20), date(2026, 7, 20))
    assert result.verdict == "unknown"


def test_missing_trigger_note_reads_unknown(wired):
    now = _et(2026, 7, 20, 5, 44)
    runlog.write_row(
        runlog.ensure_table(wired),
        runlog.build_row(
            run_id=runlog.make_run_id(now), job="site",
            started_at=now, ended_at=now, status="success",
            items_in=1, items_out=1, notes="no trigger recorded",
        ),
    )
    (result,) = timeliness.late_days(wired, date(2026, 7, 20), date(2026, 7, 20))
    assert result.trigger == "unknown"
    assert result.late is False


def test_report_counts_measured_and_unmeasured(wired):
    _seed_site_row(wired, ended_at=_et(2026, 7, 20, 8, 52))
    _seed_site_row(wired, ended_at=_et(2026, 7, 22, 5, 44))
    report = timeliness.format_report(
        timeliness.late_days(wired, date(2026, 7, 20), date(2026, 7, 22))
    )
    assert "1 late of 2 measured, 1 unmeasured" in report
