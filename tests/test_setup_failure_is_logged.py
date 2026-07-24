"""Finding 1: a job that fails during setup still logs a row (SPEC section 8).

Before logged_run, config load, catalog connect, and the first data read all
ran outside the try whose finally wrote the run_log row. A failure there, an
unreachable R2 at 6am being the likeliest, escaped run() as a bare traceback
and left no row at all. These tests inject exactly that failure into each of
the five entry points and assert the outcome the finding is about: a clean
non-zero exit AND a `failed` row in the log.

Each test would FAIL before this change, because run() raised and no row was
written.
"""
from __future__ import annotations

from datetime import date

import pytest

from src import archive, collector, runlog
from src.audio import run_audio
from src.editor import run_edition
from src.silver import run_silver

BOOM = lambda *a, **k: (_ for _ in ()).throw(OSError("R2 unreachable"))
DAY = date(2026, 7, 19)


def _rows(catalog):
    return runlog.ensure_table(catalog).scan().to_arrow().to_pylist()


@pytest.fixture
def log_to_local(local_catalog, monkeypatch):
    # The row must land somewhere readable. logged_run resolves get_catalog at
    # call time, so pointing runlog.get_catalog at the local catalog captures
    # the row even though the job's own catalog access is what fails.
    monkeypatch.setattr(runlog, "get_catalog", lambda: local_catalog)
    return local_catalog


def test_editor_setup_failure_is_logged(log_to_local, monkeypatch):
    monkeypatch.setattr(run_edition, "get_catalog", BOOM)
    rc = run_edition.run(DAY)
    assert rc == 1
    rows = _rows(log_to_local)
    assert len(rows) == 1
    assert rows[0]["job"] == "editor" and rows[0]["status"] == "failed"
    assert "OSError" in rows[0]["notes"]


def test_silver_setup_failure_is_logged(log_to_local, monkeypatch):
    monkeypatch.setattr(run_silver, "get_catalog", BOOM)
    rc = run_silver.run(DAY)
    assert rc == 1
    rows = _rows(log_to_local)
    assert len(rows) == 1
    assert rows[0]["job"] == "silver" and rows[0]["status"] == "failed"


def test_archive_setup_failure_is_logged(log_to_local, monkeypatch):
    monkeypatch.setattr(archive, "get_catalog", BOOM)
    rc = archive.run(DAY)
    assert rc == 1
    rows = _rows(log_to_local)
    assert len(rows) == 1
    assert rows[0]["job"] == "archive" and rows[0]["status"] == "failed"


def test_audio_setup_failure_is_logged(log_to_local, monkeypatch):
    # Audio's first setup call is get_pipeline (config load); a failure there
    # is the analogue of the unreachable-catalog case for this stage.
    monkeypatch.setattr(run_audio, "get_pipeline", BOOM)
    rc = run_audio.run(DAY)
    assert rc == 1
    rows = _rows(log_to_local)
    assert len(rows) == 1
    assert rows[0]["job"] == "audio" and rows[0]["status"] == "failed"


def test_collector_setup_failure_is_logged(log_to_local, monkeypatch):
    monkeypatch.setattr(collector, "get_pipeline", BOOM)
    rc = collector.collect()
    assert rc == 1
    rows = _rows(log_to_local)
    assert len(rows) == 1
    assert rows[0]["job"] == "collector" and rows[0]["status"] == "failed"
