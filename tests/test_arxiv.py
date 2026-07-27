"""arXiv adapter fetch retry (SPEC 6.1, Finding 7).

arXiv's query API is the pipeline's flakiest source: measured on prod, 8 of 10
collector failures were ReadTimeouts, one a 429, one a 406. These drive the
new bounded retry through httpx.MockTransport, offline, with sleep stubbed so
the backoff costs no wall-clock time.
"""
from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from src.adapters import arxiv
from src.adapters.arxiv import ArxivAdapter
from src.adapters.base import user_agent

SINCE = datetime(2020, 1, 1, tzinfo=UTC)
RUN_ID = "20260719T110003Z-a4f2"

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>A learning result</title>
    <link href="http://arxiv.org/abs/2401.00001v1"/>
    <published>2026-07-25T00:00:00Z</published>
    <summary>We show a thing about models.</summary>
    <author><name>A Researcher</name></author>
  </entry>
</feed>"""


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # The retry backoff must not slow the suite.
    monkeypatch.setattr(arxiv.time, "sleep", lambda _s: None)


def _adapter(client) -> ArxivAdapter:
    return ArxivAdapter(topic_hint="ai", max_items=10, run_id=RUN_ID, client=client)


class _Sequence:
    """A MockTransport handler that yields queued responses/exceptions in turn,
    recording each request so headers can be asserted."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome  # an httpx.Response


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_succeeds_after_two_timeouts():
    handler = _Sequence([
        httpx.ReadTimeout("timed out"),
        httpx.ReadTimeout("timed out"),
        httpx.Response(200, text=ATOM),
    ])
    items = _adapter(_client(handler)).fetch(SINCE)
    assert len(items) == 1
    assert items[0].title == "A learning result"
    assert len(handler.requests) == 3  # two failed, one succeeded


def test_retries_a_429_then_succeeds():
    handler = _Sequence([
        httpx.Response(429, text="slow down"),
        httpx.Response(200, text=ATOM),
    ])
    items = _adapter(_client(handler)).fetch(SINCE)
    assert len(items) == 1
    assert len(handler.requests) == 2


def test_gives_up_after_max_attempts():
    # Three straight timeouts exhaust the retry and re-raise, so run_adapter
    # records the error and the cycle stays partial (never worse).
    handler = _Sequence([httpx.ReadTimeout("t")] * 3)
    with pytest.raises(httpx.TimeoutException):
        _adapter(_client(handler)).fetch(SINCE)
    assert len(handler.requests) == 3


def test_a_non_transient_status_does_not_retry():
    # A 404 is not transient: fail immediately rather than hammering.
    handler = _Sequence([httpx.Response(404, text="gone")])
    with pytest.raises(httpx.HTTPStatusError):
        _adapter(_client(handler)).fetch(SINCE)
    assert len(handler.requests) == 1


def test_request_carries_accept_and_user_agent():
    handler = _Sequence([httpx.Response(200, text=ATOM)])
    _adapter(_client(handler)).fetch(SINCE)
    req = handler.requests[0]
    assert req.headers["Accept"] == "application/atom+xml"
    assert req.headers["User-Agent"] == user_agent()
