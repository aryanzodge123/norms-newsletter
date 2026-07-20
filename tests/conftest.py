"""Shared test fixtures.

Every test in this suite runs offline. Network-facing adapters are driven
through httpx.MockTransport, and Iceberg writes go to a local sqlite
catalog rather than R2, so the deterministic layers can be verified
without credentials (CLAUDE.md rule 4).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pyiceberg.catalog.sql import SqlCatalog

FIXTURES = Path(__file__).parent / "fixtures"


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
