"""The degraded-publication check (SPEC section 8, decision #27).

It reads today's editor run_log row and exits non-zero only when that row is
degraded. This is the code behind the final publish-workflow step, so its exit
code is the alert.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src import degraded_check, runlog

DAY = date(2026, 7, 19)


def _seed_editor_row(catalog, *, reasons, status="partial", when=None):
    now = when or datetime.now(UTC).replace(year=2026, month=7, day=19)
    runlog.write_row(
        runlog.ensure_table(catalog),
        runlog.build_row(
            run_id=runlog.make_run_id(now), job="editor",
            started_at=now, ended_at=now, status=status,
            items_in=1, items_out=1, reasons=reasons,
        ),
    )


@pytest.fixture
def wired(local_catalog, monkeypatch):
    monkeypatch.setattr(degraded_check, "get_catalog", lambda: local_catalog)
    monkeypatch.setattr(runlog, "get_catalog", lambda: local_catalog)
    return local_catalog


def test_degraded_row_exits_nonzero(wired):
    _seed_editor_row(wired, reasons=["assembly_fallback"])
    assert degraded_check.run(DAY) == 1


def test_editor_invalid_also_flags(wired):
    _seed_editor_row(wired, reasons=["editor_invalid_fallback"])
    assert degraded_check.run(DAY) == 1


def test_thin_day_fallback_is_not_degraded(wired):
    # The key precision: a thin day is correct behavior, not a defect.
    _seed_editor_row(wired, reasons=["thin_day_fallback"])
    assert degraded_check.run(DAY) == 0


def test_a_clean_partial_is_not_degraded(wired):
    _seed_editor_row(wired, reasons=["thin_grounding", "headline_repeat"])
    assert degraded_check.run(DAY) == 0


def test_no_editor_row_is_not_flagged(wired):
    # A day that never published is the healthcheck's concern, not this one.
    assert degraded_check.run(DAY) == 0


def test_latest_editor_row_decides(wired):
    # A re-run day: an early degraded attempt followed by a clean re-run must
    # read as not degraded, because the last row is what shipped.
    early = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)
    late = datetime(2026, 7, 19, 10, 5, tzinfo=UTC)
    _seed_editor_row(wired, reasons=["assembly_fallback"], when=early)
    _seed_editor_row(wired, reasons=["thin_grounding"], when=late)
    assert degraded_check.run(DAY) == 0


def test_another_jobs_degraded_row_does_not_count(wired):
    # Only the editor row drives the publish signal. A degraded-looking code on
    # a different job must not trip it. (Constructed case; kept for safety.)
    now = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)
    runlog.write_row(
        runlog.ensure_table(wired),
        runlog.build_row(
            run_id="x", job="archive", started_at=now, ended_at=now,
            status="partial", items_in=0, items_out=0,
            reasons=["assembly_fallback"],
        ),
    )
    assert degraded_check.run(DAY) == 0
