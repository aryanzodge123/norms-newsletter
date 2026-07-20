"""The DST-correct publish gate (SPEC 6.8, decision #7).

The two crons fire at 10:00 and 11:00 UTC. Exactly one of them is 06:00 US
Eastern on any given date, and which one flips at the DST boundaries. These
tests pin that so a clock change never doubles or skips a publish.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.schedule import is_publish_time


def _utc(y, m, d, hour, minute=0) -> datetime:
    return datetime(y, m, d, hour, minute, tzinfo=UTC)


def test_summer_publishes_at_10_utc():
    # July is EDT (UTC-4): 10:00 UTC is 06:00 Eastern.
    assert is_publish_time(_utc(2026, 7, 20, 10)) is True
    assert is_publish_time(_utc(2026, 7, 20, 11)) is False


def test_winter_publishes_at_11_utc():
    # January is EST (UTC-5): 11:00 UTC is 06:00 Eastern.
    assert is_publish_time(_utc(2026, 1, 20, 11)) is True
    assert is_publish_time(_utc(2026, 1, 20, 10)) is False


def test_spring_forward_day_is_edt():
    # 2026-03-08, clocks jump to EDT at 02:00; 06:00 local is 10:00 UTC.
    assert is_publish_time(_utc(2026, 3, 8, 10)) is True
    assert is_publish_time(_utc(2026, 3, 8, 11)) is False


def test_fall_back_day_is_est():
    # 2026-11-01, clocks fall to EST at 02:00; 06:00 local is 11:00 UTC.
    assert is_publish_time(_utc(2026, 11, 1, 11)) is True
    assert is_publish_time(_utc(2026, 11, 1, 10)) is False


def test_day_before_spring_forward_is_est():
    # 2026-03-07 is still EST: 06:00 local is 11:00 UTC.
    assert is_publish_time(_utc(2026, 3, 7, 11)) is True
    assert is_publish_time(_utc(2026, 3, 7, 10)) is False


def test_off_the_hour_is_never_publish_time():
    # A manual trigger at 10:30 UTC in summer is 06:30 Eastern, not 06:00.
    assert is_publish_time(_utc(2026, 7, 20, 10, 30)) is False


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        is_publish_time(datetime(2026, 7, 20, 10, 0))
