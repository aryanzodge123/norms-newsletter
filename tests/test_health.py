"""healthchecks.io pings (SPEC section 8).

Two invariants the pipeline depends on: a missing URL is a silent no-op, and
a ping never raises, because monitoring must never change what the pipeline
does. httpx is driven through a MockTransport so no request leaves the box.
"""

from __future__ import annotations

import httpx
import pytest

from src import health


def _mock_client(recorder, *, status=200, boom=False):
    def handler(request: httpx.Request) -> httpx.Response:
        recorder.append(str(request.url))
        if boom:
            raise httpx.ConnectError("no network")
        return httpx.Response(status)

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def patch_post(monkeypatch):
    """Route health.ping's httpx.post through whatever transport a test sets."""
    state = {"transport": None, "calls": []}

    def fake_post(url, **kwargs):
        transport = state["transport"]
        with httpx.Client(transport=transport) as client:
            return client.post(url)

    monkeypatch.setattr(health.httpx, "post", fake_post)
    return state


def test_no_url_is_a_noop(patch_post):
    assert health.ping(None) is False
    assert health.ping("") is False
    assert patch_post["calls"] == []


def test_success_pings_the_bare_url(patch_post):
    calls = patch_post["calls"]
    patch_post["transport"] = _mock_client(calls)
    assert health.ping("https://hc.example/abc", health.SUCCESS) is True
    assert calls == ["https://hc.example/abc"]


def test_start_and_fail_append_the_signal(patch_post):
    calls = patch_post["calls"]
    patch_post["transport"] = _mock_client(calls)
    assert health.ping("https://hc.example/abc", health.START) is True
    assert health.ping("https://hc.example/abc/", health.FAIL) is True
    assert calls == ["https://hc.example/abc/start", "https://hc.example/abc/fail"]


def test_network_error_is_swallowed(patch_post):
    calls = patch_post["calls"]
    patch_post["transport"] = _mock_client(calls, boom=True)
    assert health.ping("https://hc.example/abc") is False


def test_non_2xx_is_swallowed(patch_post):
    calls = patch_post["calls"]
    patch_post["transport"] = _mock_client(calls, status=500)
    assert health.ping("https://hc.example/abc") is False
