"""Joining silver clusters back to bronze items (SPEC 6.5).

silver.story_clusters carries no URLs and no member text; edition.json
needs both. build_contexts is the join, and the grounding measure it
computes is what the writer-stage gate later tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.editor.context import build_contexts, retrieve_prior_mentions

from tests.conftest import make_item


def silver_row(cluster_id, member_ids, *, score=5, topic="Tech"):
    return {
        "cluster_id": cluster_id,
        "headline": f"Headline {cluster_id}",
        "summary_seed": "Seed text.",
        "topic": topic,
        "score": score,
        "rationale": "because",
        "confidence": 0.7,
        "member_ids": member_ids,
        "member_count": len(member_ids),
        "sources": ["hackernews"],
        "scored_at": datetime.now(UTC),
    }


def test_join_resolves_sources_and_urls():
    a = make_item("https://x.invalid/a", source="hackernews", body="Body text here that grounds.")
    b = make_item("https://x.invalid/b", source="arstechnica", body="")
    rows = {"c1": silver_row("c1", [a.item_id, b.item_id])}
    contexts = build_contexts(rows, [a, b])
    assert len(contexts) == 1
    ctx = contexts[0]
    names = {s["name"] for s in ctx.sources}
    assert names == {"hackernews", "arstechnica"}
    assert all(s["url"] for s in ctx.sources)


def test_null_scored_clusters_are_dropped():
    a = make_item("https://x.invalid/a")
    rows = {
        "c1": silver_row("c1", [a.item_id], score=7),
        "c2": {**silver_row("c2", [a.item_id]), "score": None},
    }
    contexts = build_contexts(rows, [a])
    assert [c.cluster_id for c in contexts] == ["c1"]


def test_clusters_with_no_members_in_bronze_are_dropped():
    a = make_item("https://x.invalid/a")
    rows = {"ghost": silver_row("ghost", ["item-not-in-bronze"])}
    assert build_contexts(rows, [a]) == []


def test_contexts_sorted_by_score_descending():
    a = make_item("https://x.invalid/a")
    rows = {
        "low": silver_row("low", [a.item_id], score=3),
        "high": silver_row("high", [a.item_id], score=9),
        "mid": silver_row("mid", [a.item_id], score=6),
    }
    contexts = build_contexts(rows, [a])
    assert [c.score for c in contexts] == [9, 6, 3]


def test_grounding_chars_sums_member_bodies():
    a = make_item("https://x.invalid/a", body="x" * 300)
    b = make_item("https://x.invalid/b", body="y" * 150)
    rows = {"c1": silver_row("c1", [a.item_id, b.item_id])}
    ctx = build_contexts(rows, [a, b])[0]
    assert ctx.grounding_chars == 450


def test_empty_bodies_ground_to_zero():
    a = make_item("https://x.invalid/a", body="")
    rows = {"c1": silver_row("c1", [a.item_id])}
    ctx = build_contexts(rows, [a])[0]
    assert ctx.grounding_chars == 0


def test_prior_mentions_empty_until_gold_exists():
    a = make_item("https://x.invalid/a")
    ctx = build_contexts({"c1": silver_row("c1", [a.item_id])}, [a])[0]
    assert retrieve_prior_mentions(ctx, a.ingest_date) == []
