"""The logged_run context manager (SPEC section 8).

The guarantee under test: exactly one run_log row is written for a real run,
whatever happens inside, and a crash becomes a clean status rather than an
escaping exception. Every job's run() leans on this, so it is tested directly
against a real local catalog.
"""
from __future__ import annotations

from src import runlog


def _rows(catalog):
    return runlog.ensure_table(catalog).scan().to_arrow().to_pylist()


def test_clean_body_writes_one_success_row(local_catalog):
    with runlog.logged_run("silver", catalog_factory=lambda: local_catalog) as rec:
        rec.items_in = 10
        rec.items_out = 9

    rows = _rows(local_catalog)
    assert len(rows) == 1
    assert rows[0]["status"] == "success"
    assert rows[0]["items_in"] == 10
    assert rows[0]["job"] == "silver"


def test_a_raise_becomes_a_failed_row_and_does_not_propagate(local_catalog):
    # The manager must swallow: a job that crashes in setup should still log
    # and let run() return a clean code, never escape as a traceback.
    with runlog.logged_run("editor", catalog_factory=lambda: local_catalog) as rec:
        raise RuntimeError("R2 unreachable")

    rows = _rows(local_catalog)
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert "RuntimeError" in rows[0]["notes"]
    assert "R2 unreachable" in rows[0]["notes"]


def test_dry_run_writes_nothing(local_catalog):
    with runlog.logged_run("archive", dry_run=True, catalog_factory=lambda: local_catalog) as rec:
        rec.items_in = 5

    assert _rows(local_catalog) == []


def test_skip_log_writes_nothing(local_catalog):
    # The editor's idempotent no-op path: the run happened but must not add a
    # row, so a re-run does not inflate the per-day editor count.
    with runlog.logged_run("editor", catalog_factory=lambda: local_catalog) as rec:
        rec.skip_log = True

    assert _rows(local_catalog) == []


def test_body_set_partial_is_kept(local_catalog):
    with runlog.logged_run("collector", catalog_factory=lambda: local_catalog) as rec:
        rec.status = "partial"
        rec.note("adapters failed: arxiv")

    rows = _rows(local_catalog)
    assert rows[0]["status"] == "partial"
    assert rows[0]["notes"] == "adapters failed: arxiv"


def test_multiple_notes_are_joined(local_catalog):
    with runlog.logged_run("editor", catalog_factory=lambda: local_catalog) as rec:
        rec.status = "partial"
        rec.note("2 stories without an article")
        rec.note("readability gate exceeded")

    assert _rows(local_catalog)[0]["notes"] == (
        "2 stories without an article; readability gate exceeded"
    )


def test_a_failed_write_is_swallowed(local_catalog, monkeypatch):
    # A run_log write that itself fails must not raise: the run already
    # happened, and the dead man's switch covers a missing row.
    monkeypatch.setattr(
        runlog, "write_row",
        lambda *a, **k: (_ for _ in ()).throw(OSError("catalog gone")),
    )
    with runlog.logged_run("silver", catalog_factory=lambda: local_catalog) as rec:
        rec.items_in = 1
    # no exception escaped; nothing to assert beyond that


def test_flags_and_cost_flow_through(local_catalog):
    with runlog.logged_run("editor", catalog_factory=lambda: local_catalog) as rec:
        rec.ai_cost_estimate_usd = 0.1234
        rec.readability_flag = True
        rec.headline_repeat_flag = False

    row = _rows(local_catalog)[0]
    assert row["ai_cost_estimate_usd"] == 0.1234
    assert row["readability_flag"] is True
    assert row["headline_repeat_flag"] is False


def test_adapter_metrics_serialized(local_catalog):
    with runlog.logged_run("collector", catalog_factory=lambda: local_catalog) as rec:
        rec.adapter_metrics = {"hackernews": {"items": 3}}

    row = _rows(local_catalog)[0]
    assert '"hackernews"' in row["adapter_metrics"]
