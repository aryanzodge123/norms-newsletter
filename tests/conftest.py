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
