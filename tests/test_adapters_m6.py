"""M6 source adapters (SPEC 6.1), all offline.

The generic RSS adapter and every bespoke adapter parse recorded payloads
directly through their split-out parse() method, so no test touches the
network or needs a key. Keyed adapters get a monkeypatched get_settings.
The final test proves the committed registry loads and every enabled
source resolves and constructs with the collector's kwargs.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.adapters.arxiv import ArxivAdapter
from src.adapters.cisa import CISAAdapter
from src.adapters.federal_register import FederalRegisterAdapter
from src.adapters.finnhub import FinnhubAdapter
from src.adapters.fred import FREDAdapter
from src.adapters.newsapi import NewsAPIAdapter
from src.adapters.rss import RSSAdapter
from src.collector import resolve_adapter
from src.config import Settings, load_sources

RUN_ID = "20260719T110003Z-a4f2"
SINCE = datetime(2026, 7, 15, 0, 0, tzinfo=UTC)
SINCE_TS = datetime.fromtimestamp(1784300000, tz=UTC)


def settings_with(**overrides) -> Settings:
    base = dict(r2_catalog_uri="x", r2_warehouse="x", r2_token="x")
    base.update(overrides)
    return Settings(**base)


# --- Generic RSS adapter -------------------------------------------------

RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>A Feed</title>
    <item>
      <title>A fresh story</title>
      <link>https://Example.com/fresh/?utm_source=rss&amp;ref=list#top</link>
      <description>&lt;p&gt;Body with a &lt;a href="x"&gt;link&lt;/a&gt;.&lt;/p&gt;</description>
      <dc:creator>Reporter One</dc:creator>
      <pubDate>Sun, 19 Jul 2026 14:30:00 +0000</pubDate>
    </item>
    <item>
      <title>A second fresh story</title>
      <link>https://example.com/second/</link>
      <description>More text.</description>
      <pubDate>Sun, 19 Jul 2026 09:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Missing date, must be skipped</title>
      <link>https://example.com/nodate/</link>
      <description>No pubDate.</description>
    </item>
    <item>
      <title>An older story outside the window</title>
      <link>https://example.com/old/</link>
      <description>Old.</description>
      <pubDate>Fri, 10 Jul 2026 11:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""


def rss_adapter(max_items: int = 40) -> RSSAdapter:
    return RSSAdapter(
        name="techcrunch",
        topic_hint="tech",
        max_items=max_items,
        run_id=RUN_ID,
        feed_url="https://techcrunch.com/feed/",
    )


def test_rss_normalizes_an_entry() -> None:
    items = rss_adapter().parse(RSS_FEED, SINCE)
    story = items[0]
    assert story.source == "techcrunch"
    assert story.source_type == "rss"
    assert story.topic_hint == "tech"
    assert story.author == "Reporter One"
    assert story.run_id == RUN_ID
    assert story.published_at == datetime(2026, 7, 19, 14, 30, tzinfo=UTC)
    # host lowercased, utm_ dropped, ref kept, fragment gone
    assert story.canonical_url == "https://example.com/fresh?ref=list"
    assert "link" in story.body_excerpt
    assert "<a href" not in story.body_excerpt
    assert len(story.item_id) == 32


def test_rss_skips_malformed_and_since_filters_old() -> None:
    titles = [i.title for i in rss_adapter().parse(RSS_FEED, SINCE)]
    assert titles == ["A fresh story", "A second fresh story"]


def test_rss_respects_max_items() -> None:
    assert len(rss_adapter(max_items=1).parse(RSS_FEED, SINCE)) == 1


def test_rss_handles_garbage_feed() -> None:
    assert rss_adapter().parse("not xml at all", SINCE) == []


def test_rss_requires_feed_url() -> None:
    with pytest.raises(ValueError, match="feed_url"):
        RSSAdapter(
            name="broken",
            topic_hint="tech",
            max_items=10,
            run_id=RUN_ID,
            feed_url=None,
        )


# --- arXiv ---------------------------------------------------------------

ARXIV_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Deep learning for widgets</title>
    <id>http://arxiv.org/abs/2607.00001v1</id>
    <link href="http://arxiv.org/abs/2607.00001v1" rel="alternate" type="text/html"/>
    <published>2026-07-19T14:30:00Z</published>
    <updated>2026-07-19T14:30:00Z</updated>
    <summary>We present a new method for widgets.</summary>
    <author><name>Ada Lovelace</name></author>
  </entry>
  <entry>
    <title>An older paper outside the window</title>
    <id>http://arxiv.org/abs/2607.00002v1</id>
    <link href="http://arxiv.org/abs/2607.00002v1" rel="alternate"/>
    <published>2026-07-10T00:00:00Z</published>
    <updated>2026-07-10T00:00:00Z</updated>
    <summary>Old work.</summary>
    <author><name>Someone Else</name></author>
  </entry>
  <entry>
    <title>Malformed, no date</title>
    <id>http://arxiv.org/abs/2607.00003v1</id>
    <link href="http://arxiv.org/abs/2607.00003v1"/>
    <summary>No date at all.</summary>
  </entry>
</feed>
"""


def arxiv_adapter(max_items: int = 40) -> ArxivAdapter:
    return ArxivAdapter(
        name="arxiv", topic_hint="ai", max_items=max_items, run_id=RUN_ID
    )


def test_arxiv_normalizes_and_filters() -> None:
    items = arxiv_adapter().parse(ARXIV_FEED, SINCE)
    assert [i.title for i in items] == ["Deep learning for widgets"]
    story = items[0]
    assert story.source == "arxiv"
    assert story.source_type == "api"
    assert story.topic_hint == "ai"
    assert story.author == "Ada Lovelace"
    assert story.published_at == datetime(2026, 7, 19, 14, 30, tzinfo=UTC)


def test_arxiv_respects_max_items() -> None:
    # A tiny cap still applies even before the since filter runs.
    assert len(arxiv_adapter(max_items=1).parse(ARXIV_FEED, SINCE)) == 1


def test_arxiv_handles_garbage() -> None:
    assert arxiv_adapter().parse("nonsense", SINCE) == []


# --- Federal Register ----------------------------------------------------

FR_PAYLOAD = {
    "results": [
        {
            "title": "Rule on widget safety",
            "html_url": "https://www.federalregister.gov/documents/2026/07/19/rule",
            "publication_date": "2026-07-19",
            "abstract": "A new safety rule.",
            "agencies": [{"name": "Consumer Product Safety Commission"}],
        },
        {
            "title": "An older rule",
            "html_url": "https://www.federalregister.gov/documents/2026/07/10/old",
            "publication_date": "2026-07-10",
            "abstract": "Old.",
        },
        {
            "title": "Malformed, no date",
            "html_url": "https://www.federalregister.gov/documents/nodate",
            "abstract": "No date.",
        },
    ]
}


def fr_adapter(max_items: int = 40) -> FederalRegisterAdapter:
    return FederalRegisterAdapter(
        name="federal_register",
        topic_hint="regulation",
        max_items=max_items,
        run_id=RUN_ID,
    )


def test_federal_register_normalizes_and_filters() -> None:
    items = fr_adapter().parse(FR_PAYLOAD, SINCE)
    assert [i.title for i in items] == ["Rule on widget safety"]
    story = items[0]
    assert story.source == "federal_register"
    assert story.source_type == "json"
    assert story.topic_hint == "regulation"
    assert story.author == "Consumer Product Safety Commission"
    assert story.published_at == datetime(2026, 7, 19, tzinfo=UTC)


def test_federal_register_respects_max_items() -> None:
    assert len(fr_adapter(max_items=1).parse(FR_PAYLOAD, SINCE)) == 1


def test_federal_register_handles_empty() -> None:
    assert fr_adapter().parse({}, SINCE) == []


# --- CISA (RSS subclass with a fixed feed) -------------------------------


def test_cisa_has_a_fixed_feed_url_without_registry_help() -> None:
    adapter = CISAAdapter(
        name="cisa", topic_hint="cyber", max_items=30, run_id=RUN_ID, feed_url=None
    )
    assert adapter.feed_url.endswith("all.xml")
    assert adapter.source_type == "rss"


def test_cisa_parses_like_rss() -> None:
    adapter = CISAAdapter(
        name="cisa", topic_hint="cyber", max_items=30, run_id=RUN_ID, feed_url=None
    )
    items = adapter.parse(RSS_FEED, SINCE)
    assert [i.title for i in items] == ["A fresh story", "A second fresh story"]
    assert items[0].source == "cisa"
    assert items[0].topic_hint == "cyber"


# --- NewsAPI (keyed) -----------------------------------------------------

NEWSAPI_PAYLOAD = {
    "status": "ok",
    "articles": [
        {
            "title": "Markets rally on new data",
            "url": "https://example.com/markets?utm_source=newsapi",
            "publishedAt": "2026-07-19T14:30:00Z",
            "description": "Stocks climbed.",
            "author": "Jane Reporter",
        },
        {
            "title": "Old headline",
            "url": "https://example.com/old",
            "publishedAt": "2026-07-10T00:00:00Z",
            "description": "Old.",
        },
        {
            "title": None,
            "url": "https://example.com/bad",
            "publishedAt": "2026-07-19T00:00:00Z",
        },
    ],
}


def test_newsapi_missing_key_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.adapters.newsapi.get_settings", lambda: settings_with(newsapi_key=None)
    )
    with pytest.raises(RuntimeError, match="NEWSAPI_KEY"):
        NewsAPIAdapter(
            name="newsapi", topic_hint="world", max_items=30, run_id=RUN_ID
        )


def test_newsapi_normalizes_and_filters(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.adapters.newsapi.get_settings", lambda: settings_with(newsapi_key="k")
    )
    adapter = NewsAPIAdapter(
        name="newsapi", topic_hint="world", max_items=30, run_id=RUN_ID
    )
    items = adapter.parse(NEWSAPI_PAYLOAD, SINCE)
    assert [i.title for i in items] == ["Markets rally on new data"]
    story = items[0]
    assert story.source_type == "json"
    assert story.topic_hint == "world"
    assert story.author == "Jane Reporter"
    assert story.canonical_url == "https://example.com/markets"


# --- Finnhub (keyed) -----------------------------------------------------

FINNHUB_PAYLOAD = [
    {
        "headline": "Fed holds rates steady",
        "url": "https://example.com/fed",
        "datetime": 1784471400,
        "summary": "No change.",
        "source": "Reuters",
    },
    {
        "headline": "Old market note",
        "url": "https://example.com/old",
        "datetime": 1784200000,
        "summary": "Old.",
    },
    {
        "headline": "",
        "url": "https://example.com/bad",
        "datetime": 1784471400,
    },
]


def test_finnhub_missing_key_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.adapters.finnhub.get_settings", lambda: settings_with(finnhub_key=None)
    )
    with pytest.raises(RuntimeError, match="FINNHUB_KEY"):
        FinnhubAdapter(
            name="finnhub", topic_hint="finance", max_items=30, run_id=RUN_ID
        )


def test_finnhub_normalizes_and_filters(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.adapters.finnhub.get_settings", lambda: settings_with(finnhub_key="k")
    )
    adapter = FinnhubAdapter(
        name="finnhub", topic_hint="finance", max_items=30, run_id=RUN_ID
    )
    items = adapter.parse(FINNHUB_PAYLOAD, SINCE_TS)
    assert [i.title for i in items] == ["Fed holds rates steady"]
    story = items[0]
    assert story.source_type == "json"
    assert story.topic_hint == "finance"
    assert story.author == "Reuters"


# --- FRED (keyed) --------------------------------------------------------

FRED_PAYLOAD = {
    "releases": [
        {
            "id": 9,
            "realtime_start": "2026-07-19",
            "realtime_end": "2026-07-19",
            "name": "Employment Situation",
            "press_release": True,
            "link": "https://www.bls.gov/eag",
        },
        {
            "id": 10,
            "realtime_start": "2026-07-19",
            "name": "Release With No Link",
        },
        {
            "id": 11,
            "realtime_start": "2026-07-10",
            "name": "An older release",
        },
        {
            "id": 12,
            "name": "Release with no date",
        },
    ]
}


def test_fred_missing_key_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.adapters.fred.get_settings", lambda: settings_with(fred_key=None)
    )
    with pytest.raises(RuntimeError, match="FRED_KEY"):
        FREDAdapter(name="fred", topic_hint="finance", max_items=30, run_id=RUN_ID)


def test_fred_normalizes_builds_url_and_filters(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.adapters.fred.get_settings", lambda: settings_with(fred_key="k")
    )
    adapter = FREDAdapter(
        name="fred", topic_hint="finance", max_items=30, run_id=RUN_ID
    )
    items = adapter.parse(FRED_PAYLOAD, SINCE)
    titles = [i.title for i in items]
    # Old release dropped by since, dateless release skipped.
    assert titles == ["Employment Situation", "Release With No Link"]
    assert items[0].canonical_url == "https://www.bls.gov/eag"
    # A release with no link falls back to the FRED release page for its id.
    assert items[1].canonical_url == "https://fred.stlouisfed.org/release?rid=10"
    assert items[0].source_type == "json"
    assert items[0].topic_hint == "finance"


# --- Registry loads and every enabled adapter constructs -----------------


def test_committed_registry_loads_and_enabled_adapters_construct() -> None:
    """config/sources.yaml resolves and constructs like the collector does."""
    sources = load_sources()
    enabled = [s for s in sources if s.enabled]
    assert enabled, "expected at least one enabled source"

    for s in enabled:
        adapter_class = resolve_adapter(s)
        adapter = adapter_class(
            name=s.name,
            topic_hint=s.topic_hint,
            max_items=s.max_items_per_run,
            run_id="x",
            shortener_hosts=(),
            feed_url=s.feed_url,
        )
        assert adapter.name == s.name
        assert adapter.topic_hint == s.topic_hint

    # Keyed sources ship disabled until their credential exists.
    disabled = {s.name for s in sources if not s.enabled}
    assert {"newsapi", "finnhub", "fred"} <= disabled
