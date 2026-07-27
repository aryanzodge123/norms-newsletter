"""The `site` run_log row (SPEC 6.11, section 8).

This row is what makes the timeliness measure possible: nothing else records
when the deploy finished. Its `notes` also carry the triggering event, which is
the only way to tell a working external trigger from a dead one, since either
scheduler alone still publishes.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from src import runlog, site_run

DAY = date(2026, 7, 20)


@pytest.fixture
def wired(local_catalog, monkeypatch, tmp_path):
    monkeypatch.setattr(runlog, "get_catalog", lambda: local_catalog)
    monkeypatch.setattr(site_run, "EDITIONS_DIR", tmp_path)
    return local_catalog


def _write_edition(tmp_path, day=DAY, *, sections=2, per_section=3, edition_type="normal"):
    edition = {
        "edition_type": edition_type,
        "sections": [
            {"stories": [{"headline": f"s{i}{j}"} for j in range(per_section)]}
            for i in range(sections)
        ],
        "briefly": [{"title": "a briefly line"}],
    }
    (tmp_path / f"{day.isoformat()}.json").write_text(json.dumps(edition))
    return edition


def _rows(catalog, job="site"):
    return [
        r
        for r in runlog.ensure_table(catalog).scan().to_arrow().to_pylist()
        if r["job"] == job
    ]


def test_writes_one_site_row(wired, tmp_path):
    _write_edition(tmp_path)
    assert site_run.run(DAY, trigger="repository_dispatch") == 0
    (row,) = _rows(wired)
    assert row["job"] == "site"
    assert row["status"] == "success"


def test_records_the_trigger_in_notes(wired, tmp_path):
    _write_edition(tmp_path)
    site_run.run(DAY, trigger="repository_dispatch")
    (row,) = _rows(wired)
    assert "trigger=repository_dispatch" in row["notes"]


def test_a_cron_trigger_is_recorded_distinctly(wired, tmp_path):
    # The distinction the migration exit criterion (SPEC 13) turns on.
    _write_edition(tmp_path)
    site_run.run(DAY, trigger="schedule")
    (row,) = _rows(wired)
    assert "trigger=schedule" in row["notes"]


def test_missing_trigger_is_recorded_as_unknown(wired, tmp_path):
    _write_edition(tmp_path)
    site_run.run(DAY)
    (row,) = _rows(wired)
    assert "trigger=unknown" in row["notes"]


def test_counts_story_cards(wired, tmp_path):
    _write_edition(tmp_path, sections=3, per_section=4)
    site_run.run(DAY, trigger="schedule")
    (row,) = _rows(wired)
    assert row["items_out"] == 12


def test_briefly_lines_are_not_counted_as_cards(wired, tmp_path):
    # items_out means "stories that got a card", per decision #3's budget.
    edition = _write_edition(tmp_path, sections=1, per_section=2)
    assert len(edition["briefly"]) == 1
    site_run.run(DAY, trigger="schedule")
    (row,) = _rows(wired)
    assert row["items_out"] == 2


def test_records_the_edition_type(wired, tmp_path):
    _write_edition(tmp_path, edition_type="fallback")
    site_run.run(DAY, trigger="schedule")
    (row,) = _rows(wired)
    assert "edition_type=fallback" in row["notes"]


def test_missing_edition_still_writes_a_row(wired):
    """The deploy happened; the row must exist even if the edition does not.

    A missing row would read as an unmeasured day in the timeliness report,
    which is a weaker signal than a partial row saying exactly what was wrong.
    """
    assert site_run.run(DAY, trigger="schedule") == 0
    (row,) = _rows(wired)
    assert row["status"] == "partial"
    assert json.loads(row["reasons"]) == [runlog.REASON_NO_EDITION]
    assert "trigger=schedule" in row["notes"]


def test_dry_run_writes_nothing(wired, tmp_path):
    _write_edition(tmp_path)
    assert site_run.run(DAY, trigger="schedule", dry_run=True) == 0
    assert _rows(wired) == []


def test_a_corrupt_edition_is_contained(wired, tmp_path):
    """logged_run must swallow the raise and still leave a row behind.

    This step is continue-on-error in the workflow, but a crash here would
    still lose the row, which is the one thing it exists to produce.
    """
    (tmp_path / f"{DAY.isoformat()}.json").write_text("{not json")
    assert site_run.run(DAY, trigger="schedule") == 1
    (row,) = _rows(wired)
    assert row["status"] == "failed"
    assert json.loads(row["reasons"]) == [runlog.REASON_RUN_FAILED]


def test_site_is_an_accepted_job_name():
    # Guards the writer: build_row validates against runlog.JOBS.
    assert "site" in runlog.JOBS
    with pytest.raises(ValueError):
        runlog.build_row(
            run_id="x", job="not-a-job",
            started_at=runlog.datetime.now(runlog.UTC),
            ended_at=runlog.datetime.now(runlog.UTC),
            status="success", items_in=0, items_out=0,
        )
