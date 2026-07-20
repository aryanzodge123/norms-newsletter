"""Adapter normalization (SPEC 6.1), driven by recorded payloads.

No network: Hacker News runs through httpx.MockTransport and Ars Technica
parses fixture text directly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from src.adapters.arstechnica import ArsTechnicaAdapter
from src.adapters.hackernews import HackerNewsAdapter, strip_html

SINCE = datetime.fromtimestamp(1784300000, tz=UTC)
RUN_ID = "20260719T110003Z-a4f2"


@pytest.fixture
def hn_client(hn_fixture) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v0/topstories.json":
            return httpx.Response(200, json=hn_fixture["topstories"])
        item_id = path.removeprefix("/v0/item/").removesuffix(".json")
        return httpx.Response(200, json=hn_fixture["items"].get(item_id))

    return httpx.Client(transport=httpx.MockTransport(handler))


def hn_adapter(client, max_items: int = 40) -> HackerNewsAdapter:
    return HackerNewsAdapter(
        topic_hint="tech", max_items=max_items, run_id=RUN_ID, client=client
    )


def ars_adapter(max_items: int = 40) -> ArsTechnicaAdapter:
    return ArsTechnicaAdapter(topic_hint="tech", max_items=max_items, run_id=RUN_ID)


# --- Hacker News ---------------------------------------------------------


def test_hn_normalizes_a_story(hn_client) -> None:
    items = hn_adapter(hn_client).fetch(SINCE)
    story = next(i for i in items if i.title == "A new compiler for the browser")

    assert story.source == "hackernews"
    assert story.source_type == "api"
    assert story.topic_hint == "tech"
    assert story.author == "pg"
    assert story.run_id == RUN_ID
    assert story.published_at == datetime.fromtimestamp(1784471400, tz=UTC)
    assert story.ingest_date == story.fetched_at.date()
    # tracking params stripped on the way into canonical_url
    assert story.canonical_url == "https://example.com/compiler"
    assert "utm_campaign" in story.url  # the raw url is preserved as fetched
    assert len(story.item_id) == 32


def test_hn_skips_non_stories_dead_and_untitled(hn_client) -> None:
    """A comment, a dead post, and a story with no title are all dropped."""
    titles = {i.title for i in hn_adapter(hn_client).fetch(SINCE)}
    assert "Dead story" not in titles
    assert not any("Not a story" in t for t in titles)
    assert len(hn_adapter(hn_client).fetch(SINCE)) == 2


def test_hn_uses_the_discussion_page_when_a_story_has_no_url(hn_client) -> None:
    items = hn_adapter(hn_client).fetch(SINCE)
    ask = next(i for i in items if i.title.startswith("Ask HN"))
    assert ask.canonical_url == "https://news.ycombinator.com/item?id=102"
    # real HN tags stripped, entities left readable
    assert "automation" in ask.body_excerpt
    assert "<i>" not in ask.body_excerpt
    assert "It's hard." in ask.body_excerpt


def test_hn_respects_since(hn_client) -> None:
    titles = {i.title for i in hn_adapter(hn_client).fetch(SINCE)}
    assert "An older story outside the since window" not in titles


def test_hn_respects_max_items_per_run(hn_client) -> None:
    assert len(hn_adapter(hn_client, max_items=1).fetch(SINCE)) == 1


def test_hn_survives_one_bad_item(hn_fixture) -> None:
    """A single failing item request is skipped, not fatal to the adapter."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v0/topstories.json":
            return httpx.Response(200, json=hn_fixture["topstories"])
        if request.url.path.endswith("/101.json"):
            return httpx.Response(500)
        item_id = request.url.path.removeprefix("/v0/item/").removesuffix(".json")
        return httpx.Response(200, json=hn_fixture["items"].get(item_id))

    items = hn_adapter(httpx.Client(transport=httpx.MockTransport(handler))).fetch(SINCE)
    assert [i.title for i in items] == ["Ask HN: How do you run a small newsroom?"]


def test_strip_html_unescapes_entities() -> None:
    assert strip_html("a &lt;i&gt;b&lt;/i&gt; c") == "a <i>b</i> c"
    assert strip_html("<p>hello</p>").strip() == "hello"
    assert strip_html(None) == ""


# --- Ars Technica --------------------------------------------------------


def test_ars_normalizes_an_entry(ars_feed) -> None:
    items = ars_adapter().parse(ars_feed, SINCE)
    story = items[0]

    assert story.source == "arstechnica"
    assert story.source_type == "rss"
    assert story.title == "Rocket lab launches its fortieth mission"
    assert story.author == "Stephen Clark"
    assert story.published_at == datetime(2026, 7, 19, 14, 30, tzinfo=UTC)
    # host lowercased, utm_* dropped, ref kept, fragment gone
    assert (
        story.canonical_url
        == "https://arstechnica.com/space/2026/07/rocket-launch?ref=list"
    )
    assert "four satellites" in story.body_excerpt
    assert "<a href" not in story.body_excerpt


def test_ars_skips_entries_missing_required_fields(ars_feed) -> None:
    """No date, no link, or no title: skipped, and the feed still parses."""
    titles = [i.title for i in ars_adapter().parse(ars_feed, SINCE)]
    assert titles == [
        "Rocket lab launches its fortieth mission",
        "A quiet update to the storage stack",
    ]


def test_ars_respects_since(ars_feed) -> None:
    titles = [i.title for i in ars_adapter().parse(ars_feed, SINCE)]
    assert "An older story outside the since window" not in titles


def test_ars_respects_max_items_per_run(ars_feed) -> None:
    assert len(ars_adapter(max_items=1).parse(ars_feed, SINCE)) == 1


def test_ars_handles_a_garbage_feed() -> None:
    """Junk in, empty list out, no exception."""
    assert ars_adapter().parse("this is not xml at all", SINCE) == []
