"""The writer stage: grounding gate, failure containment, quote lint.

Anthropic is stubbed at the client boundary, the same seam
tests/test_score.py uses. No network, no key.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from src.config import EditorConfig
from src.editor import run_writers
from src.editor.context import StoryContext
from src.editor.schema import Quote

from tests.conftest import make_item


# --------------------------------------------------------------------------
# A stub Anthropic client
# --------------------------------------------------------------------------
class _Usage:
    input_tokens = 100
    output_tokens = 50
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = _Usage()


class FakeMessages:
    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return _Response(reply)


class FakeClient:
    def __init__(self, replies):
        self.messages = FakeMessages(replies)


def valid_article(**overrides) -> str:
    article = {
        "background": "Some background that a reader needs.",
        "what_happened": "The event, stated plainly and in order.",
        "why_it_matters": "What it means for a normal person.",
        "quote": None,
    }
    article.update(overrides)
    return json.dumps(article)


@pytest.fixture
def config() -> EditorConfig:
    return EditorConfig(
        editor_model="claude-sonnet-4-5-20250929",
        writer_model="claude-haiku-4-5-20251001",
        max_retries=1,
        writer_concurrency=6,
        min_grounding_chars=400,
        min_clusters_for_normal=12,
        min_clusters_for_quiet=3,
    )


def context_with_body(body: str, *, cluster_id="c1", source="hackernews", url="https://x.invalid/a") -> StoryContext:
    item = make_item(url, source=source, body=body)
    return StoryContext(
        cluster_id=cluster_id,
        headline="A headline",
        summary_seed="A summary.",
        topic="Tech",
        score=7,
        rationale="because",
        confidence=0.8,
        member_count=1,
        members=(item,),
    )


SYSTEM = "system prompt"
TODAY = date(2026, 7, 20)


# --------------------------------------------------------------------------
# Grounding gate (decision #16)
# --------------------------------------------------------------------------
def test_below_floor_makes_no_call_and_yields_null_article(config):
    client = FakeClient([])  # any call would IndexError
    ctx = context_with_body("x" * 100)  # below 400
    result = run_writers.write_one(client, ctx, config, SYSTEM, TODAY)
    assert result.article is None
    assert result.status == "skipped_grounding"
    assert client.messages.calls == 0


def test_at_floor_makes_one_call(config):
    client = FakeClient([valid_article()])
    ctx = context_with_body("x" * 400)  # at the floor
    result = run_writers.write_one(client, ctx, config, SYSTEM, TODAY)
    assert result.article is not None
    assert result.status == "written"
    assert client.messages.calls == 1


# --------------------------------------------------------------------------
# Failure containment (SPEC 6.5): invalid twice -> null article
# --------------------------------------------------------------------------
def test_invalid_twice_yields_null_article(config):
    client = FakeClient(["not json", "still not json"])
    ctx = context_with_body("x" * 500)
    result = run_writers.write_one(client, ctx, config, SYSTEM, TODAY)
    assert result.article is None
    assert result.status == "failed_validation"
    assert client.messages.calls == 2  # one retry, per max_retries=1


def test_retry_succeeds_on_second_attempt(config):
    client = FakeClient(["not json", valid_article()])
    ctx = context_with_body("x" * 500)
    result = run_writers.write_one(client, ctx, config, SYSTEM, TODAY)
    assert result.article is not None
    assert client.messages.calls == 2


# --------------------------------------------------------------------------
# Quote lint (decision #15): strip, do not lose the article
# --------------------------------------------------------------------------
def test_good_quote_kept(config):
    quote = {
        "text": "We fixed it fast.",
        "attribution": "Sam Torres, maintainer",
        "source_url": "https://x.invalid/a",
    }
    client = FakeClient([valid_article(quote=quote)])
    ctx = context_with_body("x" * 500, url="https://x.invalid/a")
    result = run_writers.write_one(client, ctx, config, SYSTEM, TODAY)
    assert result.article["quote"]["text"] == "We fixed it fast."


def test_quote_with_foreign_source_url_is_stripped(config):
    quote = {
        "text": "We fixed it fast.",
        "attribution": "Sam Torres, maintainer",
        "source_url": "https://elsewhere.invalid/not-ours",
    }
    client = FakeClient([valid_article(quote=quote)])
    ctx = context_with_body("x" * 500, url="https://x.invalid/a")
    result = run_writers.write_one(client, ctx, config, SYSTEM, TODAY)
    assert result.article is not None       # article survives
    assert result.article["quote"] is None  # quote dropped


def test_lint_quote_drops_over_length():
    long_text = "word " * 100
    quote = Quote.model_construct(
        text=long_text, attribution="Someone", source_url="https://x.invalid/a"
    )
    assert run_writers.lint_quote(quote, {"https://x.invalid/a"}) is None


# --------------------------------------------------------------------------
# Parallel run keys results by cluster_id
# --------------------------------------------------------------------------
def test_run_writers_keys_by_cluster_id(config):
    client = FakeClient([valid_article(), valid_article()])
    contexts = [
        context_with_body("x" * 500, cluster_id="a", url="https://x.invalid/a"),
        context_with_body("y" * 500, cluster_id="b", url="https://x.invalid/b"),
    ]
    results = run_writers.run_writers(client, contexts, config, SYSTEM, TODAY)
    assert set(results) == {"a", "b"}
    assert all(r.article is not None for r in results.values())
