"""Silver run orchestration: carry-forward and the prompt assembly.

Decision #6 is the expensive rule to get wrong. Re-scoring everything
every three hours would multiply the scoring bill by eight and produce no
new information, so the carry-forward is tested directly rather than only
through the run.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from src.silver.cluster import Cluster
from src.silver.run_silver import carry_forward, load_system_prompt
from tests.conftest import make_item

SCORED_AT = datetime(2026, 7, 19, 11, 30, tzinfo=UTC)


def a_cluster(n: int) -> Cluster:
    c = Cluster()
    for i in range(n):
        c.add(make_item(f"https://example.com/{i}"), np.array([1.0]))
    return c


def stored(cluster: Cluster, *, member_count: int | None = None, score: int | None = 7) -> dict:
    return {
        cluster.cluster_id: {
            "cluster_id": cluster.cluster_id,
            "member_count": member_count if member_count is not None else len(cluster.members),
            "score": score,
            "topic": "AI" if score is not None else None,
            "rationale": "Because." if score is not None else None,
            "confidence": 0.9 if score is not None else None,
            "model_version": "claude-haiku-4-5-20251001",
            "prompt_version": "scoring_v1",
            "scored_at": SCORED_AT,
        }
    }


class TestCarryForward:
    def test_an_unchanged_cluster_is_not_rescored(self) -> None:
        cluster = a_cluster(2)
        result = carry_forward(stored(cluster), cluster)
        assert result is not None
        assert result.score == 7
        assert result.scored_at == SCORED_AT, "keeps the original scoring time"
        assert result.cost_usd == 0.0

    def test_a_grown_cluster_is_rescored(self) -> None:
        """SPEC 6.4c: clusters whose member count changed get scored again."""
        cluster = a_cluster(3)
        assert carry_forward(stored(cluster, member_count=2), cluster) is None

    def test_a_shrunken_cluster_is_rescored(self) -> None:
        cluster = a_cluster(2)
        assert carry_forward(stored(cluster, member_count=3), cluster) is None

    def test_a_new_cluster_is_scored(self) -> None:
        assert carry_forward({}, a_cluster(1)) is None

    def test_a_stored_null_score_is_retried(self) -> None:
        """A null score is a failure to retry, not a result to preserve."""
        cluster = a_cluster(1)
        assert carry_forward(stored(cluster, score=None), cluster) is None

    def test_a_different_cluster_id_does_not_match(self) -> None:
        cluster = a_cluster(1)
        other = Cluster()
        other.add(make_item("https://example.com/elsewhere"), np.array([1.0]))
        assert carry_forward(stored(other), cluster) is None


class TestSystemPrompt:
    def test_includes_the_voice_standard_and_the_rubric(self) -> None:
        """CLAUDE.md: every prompt includes prompts/voice.md."""
        prompt = load_system_prompt()
        assert "Voice standard" in prompt
        assert "Scoring rubric v1" in prompt

    def test_contains_an_anchor_for_every_spec_topic(self) -> None:
        from src.silver.score import TOPICS

        prompt = load_system_prompt()
        for topic in TOPICS:
            assert f"### {topic}" in prompt, f"no worked anchors for {topic}"

    def test_uses_no_em_dashes(self) -> None:
        """CLAUDE.md rule 7, checked where it is easy to break by accident."""
        assert "—" not in load_system_prompt()

    def test_is_long_enough_for_prompt_caching(self) -> None:
        """Haiku 4.5 silently declines to cache a prefix under 4096 tokens.

        A rough characters-per-token estimate is enough here; the real
        count is checked against the API in ensure_cacheable().
        """
        from src.silver.score import MIN_CACHEABLE_TOKENS

        estimated_tokens = len(load_system_prompt()) / 4
        assert estimated_tokens > MIN_CACHEABLE_TOKENS, (
            f"prompt is roughly {estimated_tokens:.0f} tokens, under the "
            f"{MIN_CACHEABLE_TOKENS} needed for caching to engage"
        )
