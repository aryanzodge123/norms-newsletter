"""Article-text enrichment (SPEC 6.1).

Fully offline: every fetch goes through httpx.MockTransport, the same seam
tests/test_adapters.py uses for Hacker News. No network, no credentials.
"""

from __future__ import annotations

import httpx
import pytest

from src import enrich
from src.config import EnrichConfig

from tests.conftest import make_item

ARTICLE_HTML = """
<html><head><title>A real article</title></head><body>
<nav>Home Sections Subscribe</nav>
<script>var tracking = 1;</script>
<style>.ad { display: none }</style>
<article>
<p>The regulator approved the device on Monday after a two year review.</p>
<p>It is the first of its kind that patients can buy without a prescription,
and it will reach pharmacies next spring at a price the agency called modest.</p>
<p>Analysts said the decision could reshape how the condition is monitored at home.</p>
</article>
</body></html>
"""


@pytest.fixture
def config() -> EnrichConfig:
    return EnrichConfig(
        enabled=True,
        min_chars=600,
        timeout_seconds=5.0,
        max_concurrency=4,
        max_bytes=2_000_000,
        skip_hosts=("news.google.com",),
        # Run the extraction in-process here so the fetch_text / enrich_items
        # tests stay fast and hermetic. The isolation wrapper has its own tests.
        isolate_extraction=False,
    )


def client_returning(response: httpx.Response | Exception) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    return httpx.Client(transport=httpx.MockTransport(handler))


def html_response(body: str = ARTICLE_HTML, **kwargs) -> httpx.Response:
    kwargs.setdefault("headers", {"content-type": "text/html; charset=utf-8"})
    return httpx.Response(200, text=body, **kwargs)


# --------------------------------------------------------------------------
# extract_text
# --------------------------------------------------------------------------
def test_extracts_article_text() -> None:
    text = enrich.extract_text(ARTICLE_HTML, isolate=False)
    assert "regulator approved the device" in text
    assert "without a prescription" in text


def test_extraction_drops_scripts_and_styles() -> None:
    text = enrich.extract_text(ARTICLE_HTML, isolate=False)
    assert "var tracking" not in text
    assert "display: none" not in text


def test_paragraph_fallback_works_without_trafilatura() -> None:
    """The fallback is what keeps the module working when trafilatura finds
    nothing it recognizes as an article."""
    text = enrich._strip_paragraphs(ARTICLE_HTML)
    assert "regulator approved the device" in text
    assert "var tracking" not in text


def test_empty_html_is_empty() -> None:
    assert enrich.extract_text("") == ""


def test_whitespace_only_html_is_empty() -> None:
    assert enrich.extract_text("   \n\t ") == ""


# --------------------------------------------------------------------------
# _run_isolated: trafilatura's segfault cannot be caught in-process, so the
# call runs in a child. These stand-in workers exercise the isolation without
# depending on trafilatura. They are top-level so spawn can pickle them.
# --------------------------------------------------------------------------
def _worker_returns_text(html: str, result_queue) -> None:
    result_queue.put("extracted: " + html)


def _worker_crashes(html: str, result_queue) -> None:
    import os

    os._exit(1)  # dies before putting anything, like a segfault


def _worker_hangs(html: str, result_queue) -> None:
    import time

    time.sleep(30)


def test_isolated_success_returns_worker_text() -> None:
    assert enrich._run_isolated(_worker_returns_text, "hi", timeout=10.0) == "extracted: hi"


def test_isolated_crash_returns_none() -> None:
    assert enrich._run_isolated(_worker_crashes, "hi", timeout=10.0) is None


def test_isolated_timeout_returns_none() -> None:
    assert enrich._run_isolated(_worker_hangs, "hi", timeout=0.5) is None


def test_isolated_crash_falls_back_to_paragraphs(monkeypatch) -> None:
    """A crashing extraction still yields the regex fallback's text, never a
    process-killing segfault reaching the caller."""
    monkeypatch.setattr(enrich, "_extract_worker", _worker_crashes)
    text = enrich.extract_text(ARTICLE_HTML, isolate=True, timeout=10.0)
    assert "regulator approved the device" in text


# --------------------------------------------------------------------------
# should_fetch
# --------------------------------------------------------------------------
def test_thin_item_is_fetched(config) -> None:
    assert enrich.should_fetch(make_item("https://x.invalid/a", body="short"), config)


def test_item_with_real_text_is_left_alone(config) -> None:
    item = make_item("https://x.invalid/a", body="x" * 700)
    assert not enrich.should_fetch(item, config)


def test_skip_hosts_are_not_fetched(config) -> None:
    item = make_item("https://news.google.com/rss/articles/CBMi123", body="short")
    assert not enrich.should_fetch(item, config)


def test_disabled_config_fetches_nothing(config) -> None:
    off = config.model_copy(update={"enabled": False})
    assert not enrich.should_fetch(make_item("https://x.invalid/a", body=""), off)


# --------------------------------------------------------------------------
# fetch_text: every failure mode returns "" rather than raising
# --------------------------------------------------------------------------
def test_fetch_returns_article_text(config) -> None:
    text = enrich.fetch_text("https://x.invalid/a", config, client_returning(html_response()))
    assert "regulator approved the device" in text


def test_error_status_returns_empty(config) -> None:
    client = client_returning(httpx.Response(404, text="nope"))
    assert enrich.fetch_text("https://x.invalid/a", config, client) == ""


def test_non_html_is_skipped(config) -> None:
    client = client_returning(
        httpx.Response(200, text="%PDF-1.4", headers={"content-type": "application/pdf"})
    )
    assert enrich.fetch_text("https://x.invalid/a.pdf", config, client) == ""


def test_oversized_body_is_skipped(config) -> None:
    small = config.model_copy(update={"max_bytes": 50})
    assert enrich.fetch_text("https://x.invalid/a", small, client_returning(html_response())) == ""


def test_timeout_returns_empty(config) -> None:
    client = client_returning(httpx.TimeoutException("too slow"))
    assert enrich.fetch_text("https://x.invalid/a", config, client) == ""


def test_connection_error_returns_empty(config) -> None:
    client = client_returning(httpx.ConnectError("no route"))
    assert enrich.fetch_text("https://x.invalid/a", config, client) == ""


# --------------------------------------------------------------------------
# enrich_items
# --------------------------------------------------------------------------
def test_enriches_a_thin_item(config) -> None:
    item = make_item("https://x.invalid/a", body="tiny")
    out, metrics = enrich_with(config, [item], html_response())
    assert "regulator approved the device" in out[0].body_excerpt
    assert metrics == {
        "considered": 1,
        "fetched": 1,
        "enriched": 1,
        "chars_added": len(out[0].body_excerpt) - len("tiny"),
    }


def test_item_id_is_unchanged_by_enrichment(config) -> None:
    """item_id derives from canonical_url and published_at, never the body,
    so enrichment cannot produce a second bronze row for the same story."""
    item = make_item("https://x.invalid/a", body="tiny")
    out, _ = enrich_with(config, [item], html_response())
    assert out[0].item_id == item.item_id
    assert out[0].canonical_url == item.canonical_url


def test_excerpt_is_truncated_to_the_spec_length(config) -> None:
    long_html = "<html><body>" + "<p>" + ("word " * 5000) + "</p></body></html>"
    item = make_item("https://x.invalid/a", body="tiny")
    out, _ = enrich_with(config, [item], html_response(long_html))
    from src.adapters.base import BODY_EXCERPT_CHARS

    assert len(out[0].body_excerpt) <= BODY_EXCERPT_CHARS


def test_failed_fetch_keeps_the_original_excerpt(config) -> None:
    item = make_item("https://x.invalid/a", body="the original blurb")
    out, metrics = enrich_with(config, [item], httpx.Response(500, text="boom"))
    assert out[0].body_excerpt == "the original blurb"
    assert metrics["fetched"] == 1 and metrics["enriched"] == 0


def test_shorter_extraction_does_not_replace_a_better_excerpt(config) -> None:
    item = make_item("https://x.invalid/a", body="x" * 500)
    thin = "<html><body><p>tiny</p></body></html>"
    out, metrics = enrich_with(config, [item], html_response(thin))
    assert out[0].body_excerpt == "x" * 500
    assert metrics["enriched"] == 0


def test_skipped_items_are_returned_untouched(config) -> None:
    google = make_item("https://news.google.com/rss/articles/CBMi", body="blurb")
    rich = make_item("https://x.invalid/b", body="y" * 700)
    out, metrics = enrich_with(config, [google, rich], html_response())
    assert [i.body_excerpt for i in out] == ["blurb", "y" * 700]
    assert metrics["fetched"] == 0


def test_order_is_preserved(config) -> None:
    items = [make_item(f"https://x.invalid/{i}", body="tiny") for i in range(4)]
    out, _ = enrich_with(config, items, html_response())
    assert [i.canonical_url for i in out] == [i.canonical_url for i in items]


def test_empty_input_is_a_noop(config) -> None:
    out, metrics = enrich.enrich_items([], config)
    assert out == [] and metrics["fetched"] == 0


# --------------------------------------------------------------------------
def enrich_with(config, items, response):
    return enrich.enrich_items(items, config, client=client_returning(response))
