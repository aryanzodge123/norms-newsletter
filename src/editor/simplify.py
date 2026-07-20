"""The readability revision pass over editor-owned text (SPEC 6.5).

The revision pass used to re-call only the writer stage, so only articles
could be fixed. But the readability gate measures every piece of generated
text, and on real editions the editor's own text graded worst: summaries at
17.0 and glance points at 14.3, against articles at 11.5. Those pieces were
measured, counted against the edition average, and then never revised, so an
edition could not get under the limit no matter how well the articles were
rewritten.

This module closes that loop. It re-calls a small model with the failing
pieces and asks for plainer versions of the same facts, then deterministic
code puts them back by id. The model rewrites prose only: it never sees or
changes which stories were selected, their order, their topics, or their
slugs, so curation stays where it was decided (rule zero).

Validator before prompt, as everywhere: SimplifyResponse is the authority on
a valid reply, and the edition is re-validated after the rewrites land.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config import EditorConfig
from . import llm, readability
from .schema import EM_DASH, _api_schema

log = logging.getLogger(__name__)

PROMPT_VERSION = "simplify_v1"
MAX_OUTPUT_TOKENS = 4096

# Ids the pass addresses. A summary is keyed by its story's slug, which is
# already unique within an edition (SPEC 6.5), so the rewrite maps back
# without ambiguity.
HEADLINE_ID = "headline"
POINT_PREFIX = "point:"
SUMMARY_PREFIX = "summary:"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SimplifiedItem(Strict):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def _clean(cls, value: str) -> str:
        cleaned = value.strip()
        if EM_DASH in cleaned:
            raise ValueError("em dash is not allowed (voice standard 8)")
        return cleaned


class SimplifyResponse(Strict):
    items: list[SimplifiedItem] = Field(default_factory=list)


# Same transform the other stages use: inline $defs, additionalProperties
# false, and drop the value constraints the API's structured-output subset
# rejects. The pydantic model above still enforces all of them.
SIMPLIFY_RESPONSE_SCHEMA = _api_schema(SimplifyResponse)


def collect_failing(edition: dict, limit: float = readability.MAX_GRADE) -> list[dict]:
    """Editor-owned pieces that read too hard, hardest first.

    Only pieces over the limit are sent. Rewriting text that already reads
    plainly costs money and risks making it worse, which is the same rule
    the writer-side revision already follows.
    """
    pieces: list[dict] = []

    headline = edition.get("headline_of_the_day")
    if headline:
        pieces.append({"id": HEADLINE_ID, "text": headline, "kind": "headline"})

    for index, point in enumerate(edition.get("key_points") or []):
        text = point.get("text")
        if text:
            pieces.append({"id": f"{POINT_PREFIX}{index}", "text": text, "kind": "glance point"})

    for section in edition.get("sections") or []:
        for story in section.get("stories") or []:
            summary = story.get("summary")
            if summary:
                pieces.append(
                    {
                        "id": f"{SUMMARY_PREFIX}{story['slug']}",
                        "text": summary,
                        "kind": "story summary",
                    }
                )

    failing = [p for p in pieces if readability.grade(p["text"]) > limit]
    failing.sort(key=lambda p: -readability.grade(p["text"]))
    return failing


def build_user_message(failing: list[dict], limit: float) -> str:
    """The failing pieces, with what each one is and how hard it reads."""
    lines = [
        f"These lines read above grade {limit:.0f}. Rewrite each one plainer, "
        "keeping every fact and name exactly as it is.",
        "",
    ]
    for piece in failing:
        lines.append(f"id: {piece['id']}")
        lines.append(f"  type: {piece['kind']}")
        lines.append(f"  grade: {readability.grade(piece['text']):.1f}")
        lines.append(f"  text: {piece['text']}")
        lines.append("")
    return "\n".join(lines)


def apply_rewrites(edition: dict, rewrites: dict[str, str]) -> int:
    """Put rewritten text back by id. Returns how many landed.

    Deterministic: the model returned prose keyed by id and nothing else, so
    structure, ordering, topics and slugs are untouched by construction.
    """
    applied = 0

    if HEADLINE_ID in rewrites:
        edition["headline_of_the_day"] = rewrites[HEADLINE_ID]
        applied += 1

    for index, point in enumerate(edition.get("key_points") or []):
        key = f"{POINT_PREFIX}{index}"
        if key in rewrites:
            point["text"] = rewrites[key]
            applied += 1

    for section in edition.get("sections") or []:
        for story in section.get("stories") or []:
            key = f"{SUMMARY_PREFIX}{story.get('slug')}"
            if key in rewrites:
                story["summary"] = rewrites[key]
                applied += 1

    return applied


def simplify_edition(
    client,
    edition: dict,
    config: EditorConfig,
    system_prompt: str,
    *,
    limit: float = readability.MAX_GRADE,
) -> tuple[int, float]:
    """Rewrite the editor-owned text that reads too hard, in place.

    Returns (pieces applied, cost). A failure here is contained the way every
    other AI failure in this stage is: the edition keeps the text it had and
    publishes flagged, rather than losing the edition.
    """
    failing = collect_failing(edition, limit)
    if not failing:
        return 0, 0.0

    log.info("simplify: %d editor-owned lines over grade %.0f", len(failing), limit)
    try:
        call = llm.call_validated(
            client,
            model=config.writer_model,
            system_prompt=system_prompt,
            user_message=build_user_message(failing, limit),
            response_model=SimplifyResponse,
            response_schema=SIMPLIFY_RESPONSE_SCHEMA,
            max_tokens=MAX_OUTPUT_TOKENS,
            max_retries=config.max_retries,
            label="simplify",
        )
    except llm.AIFailure as failure:
        log.warning("simplify failed, keeping the original text: %s", failure)
        return 0, failure.cost_usd

    wanted = {piece["id"] for piece in failing}
    rewrites = {
        item.id: item.text
        for item in call.value.items
        # Only ids we asked about, and only rewrites that actually read
        # easier. A "simplification" that grades worse is not one.
        if item.id in wanted
        and readability.grade(item.text)
        < readability.grade(next(p["text"] for p in failing if p["id"] == item.id))
    }
    applied = apply_rewrites(edition, rewrites)
    log.info("simplify: applied %d of %d rewrites", applied, len(failing))
    return applied, call.cost_usd
