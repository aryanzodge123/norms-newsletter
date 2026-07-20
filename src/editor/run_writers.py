"""Stage 2: the writer stage (SPEC 6.5).

One small call per story, run in parallel. Each produces the `article`
block for one story from that story's cluster excerpts plus any prior
mentions. Two failures are contained per story, never per edition:

  - a story below the grounding floor gets article: null and no call is
    made (decision #16: no article without something to ground it on);
  - a story whose article is invalid twice gets article: null (SPEC 6.5).

Both mark the run partial. The quote policy (decision #15) is enforced in
code after validation, not merely asked for in the prompt.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..config import REPO_ROOT, EditorConfig
from . import llm
from .context import StoryContext, retrieve_prior_mentions
from .schema import WRITER_RESPONSE_SCHEMA, Quote, WriterResponse

log = logging.getLogger(__name__)

PROMPT_VERSION = "writer_v1"
PROMPTS_DIR = REPO_ROOT / "prompts"
MAX_OUTPUT_TOKENS = 2048

# Decision #15: "short (1-2 sentences)". The schema caps it at 320 chars;
# this is the same cap the lint applies so a borderline quote is stripped
# rather than failing the whole article's validation.
QUOTE_MAX_CHARS = 320


@dataclass(frozen=True)
class ArticleResult:
    """One story's article outcome. article is None on either failure path."""

    cluster_id: str
    article: dict | None
    cost_usd: float
    status: str  # "written" | "skipped_grounding" | "failed_validation"


def load_system_prompt(prompts_dir: Path | None = None) -> str:
    prompts_dir = prompts_dir or PROMPTS_DIR
    voice = (prompts_dir / "voice.md").read_text()
    guide = (prompts_dir / "writer_v1.md").read_text()
    return f"{voice}\n\n---\n\n{guide}"


def build_user_message(
    context: StoryContext,
    prior_mentions: list[dict],
    revision_sentences: list[str] | None = None,
) -> str:
    parts = [
        f"Title (as the editor wrote it): {context.headline}",
        f"Summary: {context.summary_seed}",
        "",
        "Source excerpts:",
        context.excerpt_block(),
        "",
        "Prior mentions:",
    ]
    if prior_mentions:
        for mention in prior_mentions:
            parts.append(f"- {mention.get('date')}: {mention.get('summary')}")
    else:
        parts.append("(none)")
    if revision_sentences:
        # SPEC 6.5 readability gate: the one automatic revision pass gets
        # the failing sentences listed. Rewriting to read more simply, not
        # a rewrite of the facts, and the grounding rule still holds.
        parts.append("")
        parts.append(
            "This story read too hard on the last pass. Rewrite it to read "
            "more simply, keeping every fact and staying within the same "
            "grounding. The gate is Flesch-Kincaid grade 9, and it is driven "
            "by two things only: words per sentence, and syllables per word. "
            "So do exactly this:"
        )
        parts.append(
            "- Keep every sentence at or under 12 words. Split any sentence "
            "joined by 'and', 'which', 'while', or a semicolon into two."
        )
        parts.append(
            "- Replace long words with short ones wherever the meaning "
            "survives: 'use' not 'utilize', 'help' not 'facilitate', 'about' "
            "not 'approximately', 'so' not 'consequently', 'buy' not "
            "'purchase', 'end' not 'termination'. Proper nouns stay as they are."
        )
        parts.append(
            "- Cut padding outright: 'in order to' is 'to', 'made the decision "
            "to' is 'decided to', 'is expected to result in' is 'will likely'."
        )
        parts.append("These sentences were the hardest, simplify them most:")
        for sentence in revision_sentences:
            parts.append(f"- {sentence}")
    return "\n".join(parts)


def lint_quote(quote: Quote | None, source_urls: set[str]) -> Quote | None:
    """Decision #15, enforced in code.

    A quote that violates the policy is dropped and the rest of the article
    is kept, because a good article with an unlinkable quote is still a
    good article. The schema already checks length and that source_url is
    one of the story's sources; this is the belt to those braces, and the
    place where "strip, do not reject" is decided.
    """
    if quote is None:
        return None
    if len(quote.text) > QUOTE_MAX_CHARS:
        log.warning("dropping over-length quote (%d chars)", len(quote.text))
        return None
    if not quote.attribution.strip():
        log.warning("dropping quote with no attribution")
        return None
    if quote.source_url not in source_urls:
        log.warning("dropping quote whose source_url is not one of the story's sources")
        return None
    return quote


def write_one(
    client,
    context: StoryContext,
    config: EditorConfig,
    system_prompt: str,
    target_date: date,
    revision_sentences: list[str] | None = None,
    catalog=None,
) -> ArticleResult:
    """Write one article, or decline to. Never raises.

    When revision_sentences is given this is the readability gate's one
    revision pass (SPEC 6.5), not a first draft. The grounding gate is not
    re-checked: a story that cleared it to get an article the first time
    still has that article, and the pass only simplifies the prose.
    """
    if revision_sentences is None and context.grounding_chars < config.min_grounding_chars:
        log.info(
            "story %s: %d grounding chars below floor %d, publishing without article",
            context.cluster_id,
            context.grounding_chars,
            config.min_grounding_chars,
        )
        return ArticleResult(context.cluster_id, None, 0.0, "skipped_grounding")

    prior = retrieve_prior_mentions(context, target_date, catalog)
    user_message = build_user_message(context, prior, revision_sentences)
    source_urls = {source["url"] for source in context.sources}

    try:
        call = llm.call_validated(
            client,
            model=config.writer_model,
            system_prompt=system_prompt,
            user_message=user_message,
            response_model=WriterResponse,
            response_schema=WRITER_RESPONSE_SCHEMA,
            max_tokens=MAX_OUTPUT_TOKENS,
            max_retries=config.max_retries,
            label=f"writer[{context.cluster_id}]",
        )
    except llm.AIFailure as failure:
        log.warning(
            "story %s article failed twice, publishing without it", context.cluster_id
        )
        return ArticleResult(context.cluster_id, None, failure.cost_usd, "failed_validation")

    response: WriterResponse = call.value  # type: ignore[assignment]
    quote = lint_quote(response.quote, source_urls)
    article = {
        "background": response.background,
        "what_happened": response.what_happened,
        "why_it_matters": response.why_it_matters,
        "quote": quote.model_dump() if quote is not None else None,
    }
    return ArticleResult(context.cluster_id, article, call.cost_usd, "written")


def run_writers(
    client,
    contexts: list[StoryContext],
    config: EditorConfig,
    system_prompt: str,
    target_date: date,
    catalog=None,
) -> dict[str, ArticleResult]:
    """Write every selected story's article, in parallel, keyed by cluster_id.

    Ordering does not matter: each call is independent (SPEC 6.5), so a
    thread pool is the whole of the parallelism. Failures are already
    contained inside write_one, so the pool never sees an exception.
    """
    if not contexts:
        return {}
    workers = min(config.writer_concurrency, len(contexts))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(
            lambda ctx: write_one(
                client, ctx, config, system_prompt, target_date, catalog=catalog
            ),
            contexts,
        )
    return {result.cluster_id: result for result in results}
