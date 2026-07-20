"""Collector orchestration (SPEC 6.1, 6.2).

The rule under test: one adapter failing never fails the run.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.adapters.base import build_item
from src.collector import resolve_adapter, run_adapter
from src.config import SourceConfig

SINCE = datetime(2026, 7, 19, 5, 0, tzinfo=UTC)
RUN_ID = "20260719T110003Z-a4f2"


def source(adapter: str = "adapters.hackernews.HackerNewsAdapter") -> SourceConfig:
    return SourceConfig(
        name="hackernews", adapter=adapter, topic_hint="tech", max_items_per_run=40
    )


def test_resolves_the_registry_path_to_a_class() -> None:
    """The SPEC 6.1 dotted form resolves under src/."""
    from src.adapters.hackernews import HackerNewsAdapter

    assert resolve_adapter(source()) is HackerNewsAdapter
    assert (
        resolve_adapter(source("adapters.arstechnica.ArsTechnicaAdapter")).name
        == "arstechnica"
    )


def test_a_missing_adapter_class_is_reported_not_raised() -> None:
    items, metrics = run_adapter(source("adapters.nope.MissingAdapter"), SINCE, RUN_ID, ())
    assert items == []
    assert metrics["errors"] == 1
    assert "ModuleNotFoundError" in metrics["error"]


def test_a_failing_adapter_is_isolated(monkeypatch) -> None:
    """Log, skip, continue (SPEC 6.1). The run survives."""

    class Exploding:
        def __init__(self, **kwargs) -> None:
            pass

        def fetch(self, since):
            raise RuntimeError("the feed went down")

    monkeypatch.setattr("src.collector.resolve_adapter", lambda s: Exploding)
    items, metrics = run_adapter(source(), SINCE, RUN_ID, ())

    assert items == []
    assert metrics["errors"] == 1
    assert "the feed went down" in metrics["error"]
    assert metrics["latency_ms"] >= 0


def test_a_healthy_adapter_reports_its_metrics(monkeypatch) -> None:
    item = build_item(
        source="hackernews",
        source_type="api",
        topic_hint="tech",
        url="https://example.com/a",
        title="A story",
        body="Body.",
        author="pg",
        published_at=SINCE,
        run_id=RUN_ID,
    )

    class Working:
        def __init__(self, **kwargs) -> None:
            pass

        def fetch(self, since):
            return [item]

    monkeypatch.setattr("src.collector.resolve_adapter", lambda s: Working)
    items, metrics = run_adapter(source(), SINCE, RUN_ID, ())

    assert items == [item]
    assert metrics == {"items": 1, "errors": 0, "latency_ms": metrics["latency_ms"]}
    assert metrics["errors"] == 0
