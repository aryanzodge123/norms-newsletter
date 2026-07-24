"""Stage 1: the editor agent (SPEC 6.5).

One Sonnet-class call. Reads today's usable clusters, applies editorial
policy (prompts/editor_v1.md), and returns the edition core: headline,
glance points, per-section story selections with titles and summaries, and
a briefly list. Invalid twice is the one edition-sized failure in this
milestone: the caller publishes a fallback edition (SPEC section 7).

The editor is never asked for a fact the pipeline already owns. Slugs,
scores, source URLs, stats, and edition_number are filled in afterward by
deterministic code. The call is small and structural facts stay out of the
model's hands (rule zero).
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import REPO_ROOT, EditorConfig
from . import llm
from .context import StoryContext
from .plan import SectionPlan
from .schema import EDITOR_RESPONSE_SCHEMA, EditorResponse

log = logging.getLogger(__name__)

PROMPT_VERSION = "editor_v1"
PROMPTS_DIR = REPO_ROOT / "prompts"
MAX_OUTPUT_TOKENS = 4096


def load_system_prompt(prompts_dir: Path | None = None) -> str:
    """The editorial policy, with the voice standard prepended.

    Same include pattern as src/silver/run_silver.py: voice.md first,
    CLAUDE.md rule 5, then the stage prompt.
    """
    prompts_dir = prompts_dir or PROMPTS_DIR
    voice = (prompts_dir / "voice.md").read_text()
    policy = (prompts_dir / "editor_v1.md").read_text()
    return f"{voice}\n\n---\n\n{policy}"


def _mode_line(edition_type: str, plan: SectionPlan) -> str:
    n_low, n_high = (4, 6) if edition_type == "normal" else (3, 3)
    lines = [
        f"Edition mode: {edition_type}.",
        f"Write {n_low} to {n_high} glance points.",
        "Available sections (use only these, two to four stories each, in "
        f"this order): {', '.join(plan.available) or 'none'}.",
    ]
    if plan.held:
        lines.append(
            "Sections that could not fill two stories, put their stories in "
            f"briefly: {', '.join(plan.held)}."
        )
    if plan.shrink:
        lines.append(
            "Several sections are dead today. Keep the edition tight rather "
            "than padding it to hit a story count."
        )
    return "\n".join(lines)


def build_user_message(
    contexts: list[StoryContext],
    edition_type: str,
    plan: SectionPlan,
    prior_coverage: dict[str, list[dict]] | None = None,
    repeat_feedback: str | None = None,
) -> str:
    """The candidate list and the constraints, as the editor sees them.

    `prior_coverage` is the edition-wide map of stories the newsletter has
    already covered, computed by code before this call (SPEC 6.5). Only
    candidates that have prior coverage carry a block, so on a normal day
    this adds a handful of lines: measured on 2026-07-23, 3 of 161.

    `repeat_feedback` is set on the headline gate's one retry and explains
    which earlier headline was restated. It mirrors how the writer stage
    takes `revision_sentences` on the readability gate's revision pass.
    """
    prior_coverage = prior_coverage or {}
    parts = [_mode_line(edition_type, plan), "", "Candidate stories:", ""]
    for context in contexts:
        sources = ", ".join(sorted({m.source for m in context.members}))
        parts.append(f"cluster_id: {context.cluster_id}")
        parts.append(f"  topic: {context.topic}")
        parts.append(f"  score: {context.score}  ({context.rationale})")
        parts.append(f"  sources ({context.member_count}): {sources}")
        parts.append(f"  headline: {context.headline}")
        excerpt = context.summary_seed.strip().replace("\n", " ")
        if excerpt:
            parts.append(f"  excerpt: {excerpt[:400]}")
        for mention in prior_coverage.get(context.cluster_id, []):
            summary = (mention.get("summary") or "").strip().replace("\n", " ")
            parts.append(f"  prior_coverage: {mention.get('date')}: {summary[:200]}")
        parts.append("")
    if repeat_feedback:
        parts.append(repeat_feedback)
        parts.append("")
    return "\n".join(parts)


def run_editor(
    client,
    contexts: list[StoryContext],
    edition_type: str,
    plan: SectionPlan,
    config: EditorConfig,
    system_prompt: str,
    prior_coverage: dict[str, list[dict]] | None = None,
    repeat_feedback: str | None = None,
) -> llm.Call:
    """One editor call. Raises llm.AIFailure if it is invalid twice."""
    user_message = build_user_message(
        contexts, edition_type, plan, prior_coverage, repeat_feedback
    )
    return llm.call_validated(
        client,
        model=config.editor_model,
        system_prompt=system_prompt,
        user_message=user_message,
        response_model=EditorResponse,
        response_schema=EDITOR_RESPONSE_SCHEMA,
        max_tokens=MAX_OUTPUT_TOKENS,
        max_retries=config.max_retries,
        label="editor",
    )
