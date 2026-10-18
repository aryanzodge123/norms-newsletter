"""Cluster scoring (SPEC 6.4c): the only AI call in the silver stage.

Rule zero (SPEC section 2): this module emits schema-validated JSON and
nothing else. The validator below is the authority on what a valid score
is, not the model and not the prompt. On a validation failure we retry
once with the error text included, then give up and return score=None so
the editor ignores the cluster (SPEC 6.4c). Failure is contained to one
cluster; the run continues.

The request also asks the API to constrain output to the schema, so a
malformed response is unlikely. That is a belt, not a replacement for the
braces: ScoreResponse still validates every reply, and the retry path is
tested, because a guarantee we do not check is a guarantee we do not have.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..config import SilverConfig, get_settings
# Pricing and reply reading are shared with the edition stages.
from ..editor import llm
from .cluster import Cluster

log = logging.getLogger(__name__)

PROMPT_VERSION = "scoring_v1"

# The SPEC 6.5 section skeleton. Constraining scoring output to exactly
# this vocabulary makes M3's section assembly a lookup rather than a
# mapping problem, and keeps the topic column usable in the weekly review.
TOPICS = (
    "Tech",
    "AI",
    "Business",
    "Finance",
    "US Politics",
    "World",
    "Regulation",
    "Science",
    "Cyber",
    "Sports",
)

Topic = Literal[
    "Tech", "AI", "Business", "Finance", "US Politics", "World",
    "Regulation", "Science", "Cyber", "Sports",
]

# The shortest prefix each model will cache, by model id prefix. Below it,
# cache_control is silently ignored: no error, just no cache. The rubric
# has to clear the bar for SPEC 6.4c's "prompt caching on" to mean
# anything, so ensure_cacheable() checks it rather than trusting it.
MIN_CACHEABLE_TOKENS: dict[str, int] = {
    "claude-haiku-4-5": 4096,
    "claude-haiku-5-5": 512,
}
# For a model not listed: the strictest known bar, so the check warns
# rather than passing on a guess.
DEFAULT_MIN_CACHEABLE_TOKENS = max(MIN_CACHEABLE_TOKENS.values())

# A reply is about 60 to 120 tokens of JSON. The headroom is for thinking,
# which Haiku 5.5 does by default and which counts against this cap. At the
# default effort it reached 447 tokens in the 2026-10-18 comparison, close
# enough to the old 512 that a day's ~190 clusters would eventually lose
# some to a max_tokens stop and a null score.
MAX_OUTPUT_TOKENS = 2048


def min_cacheable_tokens(model: str) -> int:
    for prefix, tokens in MIN_CACHEABLE_TOKENS.items():
        if model.startswith(prefix):
            return tokens
    return DEFAULT_MIN_CACHEABLE_TOKENS


class ScoreResponse(BaseModel):
    """One scoring result. The authority on what the model may return."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    score: int = Field(ge=1, le=10)
    topic: Topic
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("rationale")
    @classmethod
    def _one_nonempty_sentence(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("rationale must not be empty")
        if "\n" in cleaned:
            raise ValueError("rationale must be a single sentence, got multiple lines")
        return cleaned


@dataclass(frozen=True)
class ScoringResult:
    """What the table stores, whether or not the model cooperated."""

    score: int | None
    topic: str | None
    rationale: str | None
    confidence: float | None
    model_version: str
    prompt_version: str
    scored_at: datetime
    cost_usd: float

    @property
    def is_null_score(self) -> bool:
        return self.score is None


def parse_response(text: str) -> ScoreResponse:
    """Parse and validate one model reply. Raises on anything invalid."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"response must be a JSON object, got {type(payload).__name__}")
    try:
        return ScoreResponse(**payload)
    except ValidationError as exc:
        raise ValueError(f"response failed schema validation: {exc}") from exc


RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "topic": {"type": "string", "enum": list(TOPICS)},
        "rationale": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["score", "topic", "rationale", "confidence"],
    "additionalProperties": False,
}


def build_user_message(cluster: Cluster) -> str:
    """The per-cluster half of the prompt. Everything volatile lives here.

    The rubric is the cached prefix, so nothing that varies per cluster
    may appear in the system prompt or the cache never reads.
    """
    lines = [
        f"Sources reporting this story: {len(cluster.members)}",
        f"Source names: {', '.join(sorted({m.source for m in cluster.members}))}",
        "",
        "Headlines and excerpts:",
    ]
    for member in cluster.members:
        excerpt = member.body_excerpt[:400].strip().replace("\n", " ")
        lines.append(f"- {member.title}")
        if excerpt:
            lines.append(f"  {excerpt}")
    return "\n".join(lines)


def estimate_cost_usd(usage, model: str) -> float:
    """Dollars for one call, from the usage block (SPEC section 8)."""
    return llm.estimate_cost_usd(usage, model)


def get_client():
    """Anthropic client. Raises here, not at import, so an M1 collector
    run never needs an M2 credential."""
    import anthropic

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is required for scoring. Set it in .env "
            "locally or as an Actions secret in CI (SETUP.md 4.2)."
        )
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def ensure_cacheable(client, system_prompt: str, model: str) -> int:
    """Confirm the rubric is long enough for prompt caching to engage.

    Returns the token count. Below the model's minimum the API accepts
    cache_control and silently declines to cache, which would quietly
    multiply the scoring bill by roughly ten. Better to know.
    """
    counted = client.messages.count_tokens(
        model=model,
        system=[{"type": "text", "text": system_prompt}],
        messages=[{"role": "user", "content": "x"}],
    ).input_tokens
    minimum = min_cacheable_tokens(model)
    if counted < minimum:
        log.warning(
            "scoring prompt is %d tokens, below the %d-token minimum for %s. "
            "Prompt caching will not engage and scoring will cost ~10x more "
            "per run. Lengthen prompts/scoring_v1.md.",
            counted,
            minimum,
            model,
        )
    return counted


def _call(client, config: SilverConfig, system_prompt: str, user_message: str):
    output_config: dict = {"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}}
    if config.scoring_effort is not None:
        output_config["effort"] = config.scoring_effort
    return client.messages.create(
        model=config.scoring_model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                # SPEC 6.4c: prompt caching on. The rubric is identical
                # for every cluster in every run, so this is read on all
                # but the first call of each 5 minute window.
                "cache_control": {"type": "ephemeral"},
            }
        ],
        output_config=output_config,
        messages=[{"role": "user", "content": user_message}],
    )


def score_cluster(
    client, cluster: Cluster, config: SilverConfig, system_prompt: str
) -> ScoringResult:
    """Score one cluster. Never raises; a failed cluster scores null.

    SPEC 6.4c: invalid twice -> score=null, editor ignores. The retry
    includes the validation error so the model can correct itself.
    """
    user_message = build_user_message(cluster)
    cost = 0.0
    last_error: str | None = None

    for attempt in range(config.scoring_max_retries + 1):
        message = user_message
        if last_error is not None:
            message = (
                f"{user_message}\n\n"
                f"Your previous reply was rejected: {last_error}\n"
                "Reply with valid JSON matching the schema exactly."
            )
        try:
            response = _call(client, config, system_prompt, message)
            cost += estimate_cost_usd(response.usage, config.scoring_model)
            parsed = parse_response(llm.response_text(response))
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            log.warning(
                "cluster %s scoring attempt %d failed: %s",
                cluster.cluster_id,
                attempt + 1,
                last_error,
            )
            continue

        return ScoringResult(
            score=parsed.score,
            topic=parsed.topic,
            rationale=parsed.rationale,
            confidence=parsed.confidence,
            model_version=config.scoring_model,
            prompt_version=PROMPT_VERSION,
            scored_at=datetime.now(UTC),
            cost_usd=cost,
        )

    log.error(
        "cluster %s could not be scored after %d attempts, storing null score",
        cluster.cluster_id,
        config.scoring_max_retries + 1,
    )
    return ScoringResult(
        score=None,
        topic=None,
        rationale=None,
        confidence=None,
        model_version=config.scoring_model,
        prompt_version=PROMPT_VERSION,
        scored_at=datetime.now(UTC),
        cost_usd=cost,
    )
