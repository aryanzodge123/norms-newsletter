"""Shared test fixtures.

Every test in this suite runs offline. Network-facing adapters are driven
through httpx.MockTransport, and Iceberg writes go to a local sqlite
catalog rather than R2, so the deterministic layers can be verified
without credentials (CLAUDE.md rule 4).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pyiceberg.catalog.sql import SqlCatalog

from src.adapters.base import build_item

FIXTURES = Path(__file__).parent / "fixtures"

RUN_ID = "20260719T110003Z-a4f2"
FETCHED = datetime(2026, 7, 19, 11, 0, 0, tzinfo=UTC)


def make_item(
    url: str,
    *,
    title: str = "A story",
    body: str = "Some body text.",
    source: str = "hackernews",
    published_at: datetime | None = None,
    fetched_at: datetime = FETCHED,
    **kwargs,
):
    """A RawItem for tests that need one but do not care about most of it."""
    return build_item(
        source=source,
        source_type="api",
        topic_hint="tech",
        url=url,
        title=title,
        body=body,
        author="pg",
        published_at=published_at or datetime(2026, 7, 19, 9, 0, tzinfo=UTC),
        run_id=RUN_ID,
        fetched_at=fetched_at,
        **kwargs,
    )


@pytest.fixture
def hn_fixture() -> dict:
    return json.loads((FIXTURES / "hn_items.json").read_text())


@pytest.fixture
def ars_feed() -> str:
    return (FIXTURES / "ars_feed.xml").read_text()


@pytest.fixture
def local_catalog(tmp_path) -> SqlCatalog:
    """A real Iceberg catalog on local disk, standing in for R2."""
    warehouse = tmp_path / "warehouse"
    warehouse.mkdir()
    return SqlCatalog(
        "test",
        uri=f"sqlite:///{tmp_path}/catalog.db",
        warehouse=f"file://{warehouse}",
    )


@pytest.fixture(scope="session")
def _runlog_guard_catalog(tmp_path_factory) -> SqlCatalog:
    """A throwaway catalog for run_log writes that no test inspects."""
    warehouse = tmp_path_factory.mktemp("runlog_guard")
    return SqlCatalog(
        "runlog_guard",
        uri=f"sqlite:///{warehouse}/catalog.db",
        warehouse=f"file://{warehouse}",
    )


@pytest.fixture(autouse=True)
def _isolate_run_log(monkeypatch, _runlog_guard_catalog):
    """Never let a test write a run_log row to production R2.

    `runlog.logged_run` resolves `runlog.get_catalog` at call time, and
    `get_catalog` reads real R2 credentials from `.env`. So any test that runs
    a job's `run()` would otherwise write a junk row (and, since Finding 3, a
    junk reason code) straight into the live `ops.run_log`, which the docstring
    above promises never happens and which the degraded-publication signal
    reads. This autouse guard points that write at a throwaway local catalog.
    A test that wants to read the row back overrides this by patching
    `runlog.get_catalog` to its own `local_catalog` after this fixture runs.
    """
    from src import runlog

    monkeypatch.setattr(runlog, "get_catalog", lambda: _runlog_guard_catalog)
