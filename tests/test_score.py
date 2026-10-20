"""Scoring validator and retry path (SPEC 6.4c, rule zero).

Anthropic is stubbed at the client boundary, so no test opens a socket.
What matters here is that the validator is the authority: every reply the
model can send is either accepted as valid or turned into a null score,
and never anything in between.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from src.config import SilverConfig
from src.silver.cluster import Cluster
from src.silver.score import (
    PROMPT_VERSION,
    TOPICS,
    ScoreResponse,
    build_user_message,
    estimate_cost_usd,
    parse_response,
    score_cluster,
)
from tests.conftest import make_item

CONFIG = SilverConfig(
    embedding_model="BAAI/bge-small-en-v1.5",
    embed_chars=500,
    cluster_threshold=0.82,
    scoring_model="claude-haiku-4-5-20251001",
    scoring_max_retries=1,
)

VALID = {
    "score": 7,
    "topic": "Regulation",
    "rationale": "A final rule with a compliance date.",
    "confidence": 0.85,
}


def a_cluster(n: int = 1) -> Cluster:
    c = Cluster()
    for i in range(n):
        c.add(make_item(f"https://example.com/{i}", title=f"Story {i}"), np.array([1.0]))
    return c


class FakeClient:
    """Returns queued replies in order, recording each request."""

    def __init__(self, *replies: str, usage: dict | None = None) -> None:
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.usage = usage or {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        if not self.replies:
            raise AssertionError("called more times than there were queued replies")
        text = self.replies.pop(0)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(**self.usage),
        )


class TestValidator:
    def test_accepts_a_valid_response(self) -> None:
        parsed = parse_response(json.dumps(VALID))
        assert parsed.score == 7
        assert parsed.topic == "Regulation"
        assert parsed.confidence == 0.85

    @pytest.mark.parametrize("topic", TOPICS)
    def test_accepts_every_spec_topic(self, topic: str) -> None:
        assert parse_response(json.dumps({**VALID, "topic": topic})).topic == topic

    def test_rejects_malformed_json(self) -> None:
        with pytest.raises(ValueError, match="not valid JSON"):
            parse_response("{score: 7,}")

    def test_rejects_a_non_object(self) -> None:
        with pytest.raises(ValueError, match="must be a JSON object"):
            parse_response("[1, 2, 3]")

    @pytest.mark.parametrize("score", [0, 11, -3, 100])
    def test_rejects_out_of_range_scores(self, score: int) -> None:
        with pytest.raises(ValueError, match="schema validation"):
            parse_response(json.dumps({**VALID, "score": score}))

    def test_rejects_a_topic_outside_the_enum(self) -> None:
        # "Weather" is outside the enum. This said "Sports" until decision
        # #32 made Sports a real topic, at which point the assertion broke.
        # Keep this value genuinely absent from TOPICS.
        assert "Weather" not in TOPICS
        with pytest.raises(ValueError, match="schema validation"):
            parse_response(json.dumps({**VALID, "topic": "Weather"}))

    def test_topic_matching_is_case_sensitive(self) -> None:
        with pytest.raises(ValueError, match="schema validation"):
            parse_response(json.dumps({**VALID, "topic": "regulation"}))

    def test_rejects_extra_keys(self) -> None:
        with pytest.raises(ValueError, match="schema validation"):
            parse_response(json.dumps({**VALID, "commentary": "I also think..."}))

    def test_rejects_missing_keys(self) -> None:
        with pytest.raises(ValueError, match="schema validation"):
            parse_response(json.dumps({"score": 7, "topic": "AI"}))

    @pytest.mark.parametrize("confidence", [-0.1, 1.1])
    def test_rejects_out_of_range_confidence(self, confidence: float) -> None:
        with pytest.raises(ValueError, match="schema validation"):
            parse_response(json.dumps({**VALID, "confidence": confidence}))

    def test_rejects_an_empty_rationale(self) -> None:
        with pytest.raises(ValueError, match="schema validation"):
            parse_response(json.dumps({**VALID, "rationale": "   "}))

    def test_rejects_a_multi_line_rationale(self) -> None:
        with pytest.raises(ValueError, match="schema validation"):
            parse_response(json.dumps({**VALID, "rationale": "One.\nTwo."}))

    def test_score_must_be_an_integer(self) -> None:
        with pytest.raises(ValueError, match="schema validation"):
            parse_response(json.dumps({**VALID, "score": 7.5}))

    def test_the_model_is_frozen(self) -> None:
        parsed = ScoreResponse(**VALID)
        with pytest.raises(Exception):
            parsed.score = 3


class TestScoreCluster:
    def test_a_valid_first_reply_is_used(self) -> None:
        client = FakeClient(json.dumps(VALID))
        result = score_cluster(client, a_cluster(), CONFIG, "RUBRIC")
        assert result.score == 7
        assert result.topic == "Regulation"
        assert result.prompt_version == PROMPT_VERSION
        assert result.model_version == CONFIG.scoring_model
        assert len(client.requests) == 1

    def test_an_invalid_reply_is_retried_once_then_accepted(self) -> None:
        client = FakeClient("not json at all", json.dumps(VALID))
        result = score_cluster(client, a_cluster(), CONFIG, "RUBRIC")
        assert result.score == 7
        assert len(client.requests) == 2

    def test_the_retry_includes_the_validation_error(self) -> None:
        # "Weather" is outside the enum, so the first reply fails validation
        # and forces the retry this test is about. Said "Sports" until
        # decision #32 made it valid, which silently removed the retry.
        client = FakeClient(json.dumps({**VALID, "topic": "Weather"}), json.dumps(VALID))
        score_cluster(client, a_cluster(), CONFIG, "RUBRIC")
        retry_text = client.requests[1]["messages"][0]["content"]
        assert "previous reply was rejected" in retry_text
        assert "schema validation" in retry_text

    def test_invalid_twice_yields_a_null_score(self) -> None:
        """SPEC 6.4c: invalid twice -> score null, editor ignores."""
        client = FakeClient("garbage", "still garbage")
        result = score_cluster(client, a_cluster(), CONFIG, "RUBRIC")
        assert result.is_null_score
        assert result.score is None
        assert result.topic is None
        assert result.rationale is None
        assert result.confidence is None
        assert len(client.requests) == 2

    def test_a_null_score_still_records_provenance(self) -> None:
        """The eval dataset needs to know what failed, not just that it did."""
        result = score_cluster(FakeClient("x", "y"), a_cluster(), CONFIG, "RUBRIC")
        assert result.model_version == CONFIG.scoring_model
        assert result.prompt_version == PROMPT_VERSION
        assert isinstance(result.scored_at, datetime)

    def test_an_api_exception_is_contained(self) -> None:
        """A failing cluster must never fail the run (SPEC section 7)."""

        class Exploding:
            def __init__(self) -> None:
                self.calls = 0
                self.messages = SimpleNamespace(create=self._create)

            def _create(self, **kwargs):
                self.calls += 1
                raise RuntimeError("connection reset")

        client = Exploding()
        result = score_cluster(client, a_cluster(), CONFIG, "RUBRIC")
        assert result.is_null_score
        assert client.calls == 2

    def test_retries_are_configurable(self) -> None:
        config = CONFIG.model_copy(update={"scoring_max_retries": 0})
        client = FakeClient("garbage")
        result = score_cluster(client, a_cluster(), config, "RUBRIC")
        assert result.is_null_score
        assert len(client.requests) == 1

    def test_cost_accumulates_across_attempts(self) -> None:
        client = FakeClient("garbage", json.dumps(VALID))
        one = score_cluster(FakeClient(json.dumps(VALID)), a_cluster(), CONFIG, "RUBRIC")
        two = score_cluster(client, a_cluster(), CONFIG, "RUBRIC")
        assert two.cost_usd == pytest.approx(one.cost_usd * 2)


class TestRequestShape:
    def test_the_rubric_is_the_cached_system_prefix(self) -> None:
        client = FakeClient(json.dumps(VALID))
        score_cluster(client, a_cluster(), CONFIG, "RUBRIC")
        system = client.requests[0]["system"]
        assert system[0]["text"] == "RUBRIC"
        assert system[0]["cache_control"] == {"type": "ephemeral"}

    def test_per_cluster_content_stays_out_of_the_cached_prefix(self) -> None:
        """Anything volatile in the system block would break every cache read."""
        client = FakeClient(json.dumps(VALID))
        c = a_cluster()
        score_cluster(client, c, CONFIG, "RUBRIC")
        assert c.seed.title not in json.dumps(client.requests[0]["system"])

    def test_output_is_schema_constrained(self) -> None:
        client = FakeClient(json.dumps(VALID))
        score_cluster(client, a_cluster(), CONFIG, "RUBRIC")
        schema = client.requests[0]["output_config"]["format"]["schema"]
        assert schema["properties"]["topic"]["enum"] == list(TOPICS)
        assert schema["additionalProperties"] is False


class TestUserMessage:
    def test_includes_every_member(self) -> None:
        message = build_user_message(a_cluster(3))
        for i in range(3):
            assert f"Story {i}" in message

    def test_reports_source_count(self) -> None:
        assert "Sources reporting this story: 3" in build_user_message(a_cluster(3))


class TestCostEstimate:
    HAIKU_45 = "claude-haiku-4-5-20251001"
    HAIKU_55 = "claude-haiku-5-5"

    @staticmethod
    def usage(**tokens) -> SimpleNamespace:
        fields = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        fields.update(tokens)
        return SimpleNamespace(**fields)

    def test_uncached_call(self) -> None:
        usage = self.usage(input_tokens=1_000_000)
        assert estimate_cost_usd(usage, self.HAIKU_45) == pytest.approx(1.00)
        assert estimate_cost_usd(usage, self.HAIKU_55) == pytest.approx(0.10)

    def test_cache_reads_are_a_tenth_of_input(self) -> None:
        usage = self.usage(cache_read_input_tokens=1_000_000)
        assert estimate_cost_usd(usage, self.HAIKU_45) == pytest.approx(0.10)
        assert estimate_cost_usd(usage, self.HAIKU_55) == pytest.approx(0.01)

    def test_output_is_priced_per_model(self) -> None:
        usage = self.usage(output_tokens=1_000_000)
        assert estimate_cost_usd(usage, self.HAIKU_45) == pytest.approx(5.00)
        assert estimate_cost_usd(usage, self.HAIKU_55) == pytest.approx(0.50)

    def test_missing_usage_fields_are_treated_as_zero(self) -> None:
        usage = SimpleNamespace(input_tokens=1_000_000)
        assert estimate_cost_usd(usage, self.HAIKU_45) == pytest.approx(1.00)


class TestEffort:
    def test_omitted_when_not_configured(self) -> None:
        """Haiku 4.5 rejects the parameter, so None must send nothing."""
        client = FakeClient(json.dumps(VALID))
        score_cluster(client, a_cluster(), CONFIG, "RUBRIC")
        assert "effort" not in client.requests[0]["output_config"]

    def test_sent_when_configured(self) -> None:
        config = CONFIG.model_copy(
            update={"scoring_model": "claude-haiku-5-5", "scoring_effort": "low"}
        )
        client = FakeClient(json.dumps(VALID))
        score_cluster(client, a_cluster(), config, "RUBRIC")
        output_config = client.requests[0]["output_config"]
        assert output_config["effort"] == "low"
        assert output_config["format"]["type"] == "json_schema"


class TestReplyWithoutText:
    """A refusal or a max_tokens stop spent on thinking carries no text block."""

    @staticmethod
    def client_returning(*responses) -> SimpleNamespace:
        queue = list(responses)
        return SimpleNamespace(messages=SimpleNamespace(create=lambda **_: queue.pop(0)))

    @staticmethod
    def reply(blocks, stop_reason="end_turn", category=None) -> SimpleNamespace:
        return SimpleNamespace(
            content=blocks,
            stop_reason=stop_reason,
            stop_details=SimpleNamespace(category=category) if category else None,
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )

    def test_thinking_first_then_text_is_read_by_type(self) -> None:
        blocks = [
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=json.dumps(VALID)),
        ]
        result = score_cluster(self.client_returning(self.reply(blocks)), a_cluster(), CONFIG, "RUBRIC")
        assert result.score == 7

    def test_refusal_twice_is_a_null_score_naming_the_reason(self, caplog) -> None:
        refusal = self.reply([], stop_reason="refusal", category="cyber")
        client = self.client_returning(refusal, refusal)
        result = score_cluster(client, a_cluster(), CONFIG, "RUBRIC")
        assert result.is_null_score
        assert "stop_reason=refusal, category=cyber" in caplog.text

    def test_max_tokens_on_thinking_is_named_too(self, caplog) -> None:
        stopped = self.reply([SimpleNamespace(type="thinking", thinking="")], stop_reason="max_tokens")
        result = score_cluster(self.client_returning(stopped, stopped), a_cluster(), CONFIG, "RUBRIC")
        assert result.is_null_score
        assert "stop_reason=max_tokens" in caplog.text


def test_topics_match_the_editor_schema():
    """score.TOPICS and editor.schema.TOPICS are duplicated and hand-synced.

    Scoring constrains `topic` to its own tuple; the editor assembles
    sections by looking topics up in its own. Nothing at runtime compares
    them, so a topic added to one and not the other would produce clusters
    the editor silently cannot place. Decision #32 added Sports to both.
    """
    from src.editor.schema import SECTION_NAMES
    from src.editor.schema import TOPICS as EDITOR_TOPICS

    assert TOPICS == EDITOR_TOPICS
    assert set(TOPICS) == set(SECTION_NAMES)
