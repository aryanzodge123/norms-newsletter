"""item_id determinism (SPEC 6.1).

item_id is the whole basis of bronze dedup. If these break, re-running the
collector duplicates rows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from src.adapters.base import make_item_id
from src.runlog import make_run_id

URL = "https://example.com/story"
WHEN = datetime(2026, 7, 19, 14, 30, tzinfo=UTC)


def test_is_32_hex_chars() -> None:
    item_id = make_item_id(URL, WHEN)
    assert len(item_id) == 32
    assert all(c in "0123456789abcdef" for c in item_id)


def test_is_stable_across_calls() -> None:
    assert make_item_id(URL, WHEN) == make_item_id(URL, WHEN)


def test_same_instant_in_another_timezone_is_the_same_id() -> None:
    """An adapter's choice of tzinfo must not change the id."""
    eastern = WHEN.astimezone(timezone(timedelta(hours=-4)))
    assert eastern != WHEN.replace(tzinfo=None)
    assert make_item_id(URL, eastern) == make_item_id(URL, WHEN)


def test_naive_timestamps_are_treated_as_utc() -> None:
    assert make_item_id(URL, WHEN.replace(tzinfo=None)) == make_item_id(URL, WHEN)


def test_different_url_gives_different_id() -> None:
    assert make_item_id(URL + "/2", WHEN) != make_item_id(URL, WHEN)


def test_different_time_gives_different_id() -> None:
    later = WHEN + timedelta(seconds=1)
    assert make_item_id(URL, later) != make_item_id(URL, WHEN)


def test_run_id_format() -> None:
    """UTC timestamp plus 4 random hex chars, e.g. 20260719T110003Z-a4f2."""
    run_id = make_run_id(datetime(2026, 7, 19, 11, 0, 3, tzinfo=UTC))
    stamp, _, suffix = run_id.partition("-")
    assert stamp == "20260719T110003Z"
    assert len(suffix) == 4
    assert all(c in "0123456789abcdef" for c in suffix)


def test_run_ids_are_unique() -> None:
    now = datetime(2026, 7, 19, 11, 0, 3, tzinfo=UTC)
    assert len({make_run_id(now) for _ in range(50)}) > 1
