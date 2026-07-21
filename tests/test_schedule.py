"""The DST-correct, delay-tolerant publish gate (SPEC 6.8, decision #7).

The two crons fire at 09:30 and 10:30 UTC. Exactly one of them is 05:30 US
Eastern on any given date, and which one flips at the DST boundaries. The gate
then publishes only if today is not already committed, so a late or repeated
firing never doubles or skips a publish. These tests pin both halves.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.schedule import should_publish, window_is_open


def _utc(y, m, d, hour, minute=0) -> datetime:
    return datetime(y, m, d, hour, minute, tzinfo=UTC)


# ---------------------------------------------------------------------------
# window_is_open: DST-correct 05:30 Eastern boundary
# ---------------------------------------------------------------------------
def test_summer_window_opens_at_0930_utc():
    # July is EDT (UTC-4): 09:30 UTC is 05:30 Eastern.
    assert window_is_open(_utc(2026, 7, 20, 9, 30)) is True
    assert window_is_open(_utc(2026, 7, 20, 9, 29)) is False


def test_winter_window_opens_at_1030_utc():
    # January is EST (UTC-5): 10:30 UTC is 05:30 Eastern.
    assert window_is_open(_utc(2026, 1, 20, 10, 30)) is True
    # The 09:30 UTC (EDT-anchored) cron lands at 04:30 Eastern in winter,
    # before the window; it must not open the window.
    assert window_is_open(_utc(2026, 1, 20, 9, 30)) is False


def test_spring_forward_day_is_edt():
    # 2026-03-08, clocks jump to EDT at 02:00; 05:30 local is 09:30 UTC.
    assert window_is_open(_utc(2026, 3, 8, 9, 30)) is True
    assert window_is_open(_utc(2026, 3, 8, 9, 29)) is False


def test_fall_back_day_is_est():
    # 2026-11-01, clocks fall to EST at 02:00; 05:30 local is 10:30 UTC.
    assert window_is_open(_utc(2026, 11, 1, 10, 30)) is True
    assert window_is_open(_utc(2026, 11, 1, 9, 30)) is False


def test_day_before_spring_forward_is_est():
    # 2026-03-07 is still EST: 05:30 local is 10:30 UTC.
    assert window_is_open(_utc(2026, 3, 7, 10, 30)) is True
    assert window_is_open(_utc(2026, 3, 7, 9, 30)) is False


def test_late_firing_is_still_inside_the_window():
    # The 2026-07-21 failure: GitHub fired the cron at 11:50 UTC (07:50 EDT).
    # The old exact-minute gate skipped the day; the window stays open.
    assert window_is_open(_utc(2026, 7, 21, 11, 50)) is True


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        window_is_open(datetime(2026, 7, 20, 9, 30))


# ---------------------------------------------------------------------------
# should_publish: window + idempotency
# ---------------------------------------------------------------------------
def test_publishes_when_open_and_not_yet_published():
    assert should_publish(_utc(2026, 7, 20, 9, 30), already_published_today=False) is True


def test_late_firing_still_publishes_when_unpublished():
    # A cron delayed to 07:50 EDT still publishes, instead of silently skipping.
    assert should_publish(_utc(2026, 7, 21, 11, 50), already_published_today=False) is True


def test_second_firing_is_a_noop_when_already_published():
    # The 10:30 UTC (06:30 EDT) firing after the 05:30 one already published.
    assert should_publish(_utc(2026, 7, 20, 10, 30), already_published_today=True) is False


def test_does_not_publish_before_window_even_if_unpublished():
    # 04:30 Eastern EST-side early cron: too early, hold.
    assert should_publish(_utc(2026, 1, 20, 9, 30), already_published_today=False) is False
