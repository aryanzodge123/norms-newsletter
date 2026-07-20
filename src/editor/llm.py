"""The AI call shape shared by both edition stages (SPEC 6.5).

Both stages follow the pattern src/silver/score.py established: ask the API
to constrain output to a schema, validate every reply anyway, retry once
with the validation error included, then fall back deterministically. This
module holds the half that is identical between them so the difference
between the editor call and the writer call stays visible.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import get_settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# USD per million tokens. Cache writes are 1.25x input, cache reads 0.1x.
# Keyed by model id prefix so a dated id resolves without a new entry.
PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-opus-4": (15.00, 75.00),
}

CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10

DEFAULT_PRICING = (3.00, 15.00)


class AIFailure(RuntimeError):
    """Every attempt failed validation. The caller decides what that costs."""

    def __init__(self, message: str, cost_usd: float):
        super().__init__(message)
        self.cost_usd = cost_usd


@dataclass(frozen=True)
class Call:
    """One completed call: the validated object and what it cost."""

    value: BaseModel
    cost_usd: float


def price_for(model: str) -> tuple[float, float]:
    for prefix, pricing in PRICING.items():
        if model.startswith(prefix):
            return pricing
    log.warning("no pricing for model %s, estimating at Sonnet rates", model)
    return DEFAULT_PRICING


def estimate_cost_usd(usage, model: str) -> float:
    """Dollars for one call, from the usage block (SPEC section 8)."""
    input_price, output_price = price_for(model)
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    uncached = getattr(usage, "input_tokens", 0) or 0
    output = getattr(usage, "output_tokens", 0) or 0
    return (
        uncached * input_price
        + write * input_price * CACHE_WRITE_MULTIPLIER
        + read * input_price * CACHE_READ_MULTIPLIER
        + output * output_price
    ) / 1_000_000


def get_client():
    """Anthropic client. Raises here, not at import, so a collector run
    never needs an edition credential."""
    import anthropic

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is required for edition generation. Set it in "
            ".env locally or as an Actions secret in CI (SETUP.md 4.2)."
        )
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def parse_into(model: type[T], text: str) -> T:
    """Parse and validate one reply. Raises ValueError on anything invalid."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(
            f"response must be a JSON object, got {type(payload).__name__}"
        )
    try:
        return model(**payload)
    except ValidationError as exc:
        raise ValueError(f"response failed schema validation: {exc}") from exc


def call_validated(
    client,
    *,
    model: str,
    system_prompt: str,
    user_message: str,
    response_model: type[T],
    response_schema: dict,
    max_tokens: int,
    max_retries: int,
    label: str,
    on_invalid: Callable[[int, str], None] | None = None,
) -> Call:
    """One AI call with validation and one retry. Raises AIFailure at the end.

    The retry carries the validation error back to the model, which is the
    difference between a retry that might work and a retry that repeats the
    same mistake. Cost accumulates across attempts because a rejected reply
    was still billed.
    """
    cost = 0.0
    last_error: str | None = None

    for attempt in range(max_retries + 1):
        message = user_message
        if last_error is not None:
            message = (
                f"{user_message}\n\n"
                f"Your previous reply was rejected: {last_error}\n"
                "Reply with valid JSON matching the schema exactly."
            )
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        # The prompt is identical for every call of a stage
                        # in a run, so this is read on all but the first.
                        # It matters most for the writer stage, which makes
                        # one call per story.
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                output_config={
                    "format": {"type": "json_schema", "schema": response_schema}
                },
                messages=[{"role": "user", "content": message}],
            )
            cost += estimate_cost_usd(response.usage, model)
            text = next(block.text for block in response.content if block.type == "text")
            value = parse_into(response_model, text)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            log.warning("%s attempt %d failed: %s", label, attempt + 1, last_error)
            if on_invalid is not None:
                on_invalid(attempt + 1, last_error)
            continue

        return Call(value=value, cost_usd=cost)

    raise AIFailure(
        f"{label} failed after {max_retries + 1} attempts: {last_error}", cost
    )
