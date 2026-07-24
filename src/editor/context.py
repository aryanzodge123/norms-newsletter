"""What the two AI stages see (SPEC 6.5).

A gap this module exists to close: `silver.story_clusters` stores `sources`
as bare names and `member_ids` as opaque strings. It carries no URLs and no
member text. edition.json needs `sources: [{name, url}]` and
`briefly: [{title, url, topic}]`, and the writer stage needs excerpts to
ground on. So the day's silver rows are joined back to the day's bronze
partition on member_ids.

Both partitions are still present when this runs: SPEC 6.9 drops them only
after the deploy, in the archival job at the end of the same workflow.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from ..adapters.base import RawItem

log = logging.getLogger(__name__)

# How much of each member's body the writer stage is shown. Enough to
# ground three paragraphs, bounded so a ten-member cluster cannot blow up
# the per-story call.
EXCERPT_CHARS = 700
MAX_EXCERPT_MEMBERS = 6


@dataclass(frozen=True)
class StoryContext:
    """One scored cluster, joined to its bronze members.

    This is the unit both stages work on and the unit the grounding gate
    tests. It is assembled by deterministic code and is the only thing the
    prompts ever see about a story.
    """

    cluster_id: str
    headline: str
    summary_seed: str
    topic: str | None
    score: int | None
    rationale: str | None
    confidence: float | None
    member_count: int
    members: tuple[RawItem, ...]

    @property
    def sources(self) -> list[dict[str, str]]:
        """Source name and URL, one per distinct source, earliest first.

        Deduplicated by name because two items from one source reporting
        one story should cite that source once, not twice.
        """
        seen: dict[str, str] = {}
        for member in self.members:
            seen.setdefault(member.source, member.canonical_url)
        return [{"name": name, "url": url} for name, url in seen.items()]

    @property
    def primary_url(self) -> str:
        """The seed member's link. Used by briefly and by fallback rows."""
        return self.members[0].canonical_url if self.members else ""

    @property
    def primary_source(self) -> str:
        return self.members[0].source if self.members else ""

    @property
    def grounding_chars(self) -> int:
        """Total body text available to write from, across all members.

        The number the writer-stage gate tests. M2 found most Hacker News
        items arrive with an empty body_excerpt, so for many clusters this
        is zero and there is genuinely nothing to ground an article on.
        """
        return sum(len(member.body_excerpt.strip()) for member in self.members)

    def excerpt_block(self) -> str:
        """The grounding text, as the writer prompt sees it."""
        lines: list[str] = []
        for member in self.members[:MAX_EXCERPT_MEMBERS]:
            excerpt = member.body_excerpt[:EXCERPT_CHARS].strip().replace("\n", " ")
            lines.append(f"[{member.source}] {member.title}")
            lines.append(f"  url: {member.canonical_url}")
            if excerpt:
                lines.append(f"  excerpt: {excerpt}")
            else:
                lines.append("  excerpt: (none available)")
        return "\n".join(lines)


def build_contexts(
    silver_rows: dict[str, dict], bronze_items: list[RawItem]
) -> list[StoryContext]:
    """Join today's clusters to today's items.

    Clusters with a null score are dropped: SPEC 6.4c says the editor
    ignores them, and a story the editor may not pick is a story that
    should not reach the budget arithmetic either.

    Returns highest score first, so the editor's global ranking starts
    from the rubric's ranking rather than from partition order.
    """
    by_id = {item.item_id: item for item in bronze_items}
    contexts: list[StoryContext] = []
    dropped_null = 0
    missing_members = 0

    for row in silver_rows.values():
        if row.get("score") is None:
            dropped_null += 1
            continue

        members = [by_id[mid] for mid in row["member_ids"] if mid in by_id]
        if not members:
            # The cluster references items that are not in the partition.
            # Nothing to link to and nothing to ground on, so it cannot
            # become a story. Counted rather than raised: one broken
            # cluster must not cost the edition.
            missing_members += 1
            continue
        members.sort(key=lambda item: (item.published_at, item.item_id))

        contexts.append(
            StoryContext(
                cluster_id=row["cluster_id"],
                headline=row["headline"],
                summary_seed=row["summary_seed"],
                topic=row["topic"],
                score=row["score"],
                rationale=row["rationale"],
                confidence=row["confidence"],
                member_count=row["member_count"],
                members=tuple(members),
            )
        )

    if dropped_null:
        log.info("dropped %d clusters with a null score (SPEC 6.4c)", dropped_null)
    if missing_members:
        log.warning(
            "dropped %d clusters whose members are absent from bronze", missing_members
        )

    contexts.sort(key=lambda c: (-(c.score or 0), c.cluster_id))
    return contexts


def retrieve_prior_mentions_batch(
    contexts: list[StoryContext],
    target_date: date,
    catalog=None,
    *,
    lookback_days: int | None = None,
) -> dict[str, list[dict]]:
    """Prior published coverage for many stories, in one pass.

    Same semantics as `retrieve_prior_mentions` for each story, but the gold
    scan and the embedding both happen once for the whole set rather than
    once per story. The single-story function was called per story inside
    the writer stage and again per failing story in each readability pass,
    so a twelve-story edition ran a dozen scans over nearly the same rows.

    Returns cluster_id -> mentions, with an entry only for stories that have
    prior coverage. Callers treat a missing key as "no prior coverage".

    `lookback_days` defaults to the writer stage's window
    (`prior_mention_lookback_days`); the editor stage passes its own,
    shorter one (SPEC 6.5).
    """
    if catalog is None or not contexts:
        return {}

    from ..config import get_pipeline
    from ..silver import cluster
    from .. import archive

    pipeline = get_pipeline()
    lookback = lookback_days or pipeline.archive.prior_mention_lookback_days
    model_name = pipeline.silver.embedding_model
    threshold = pipeline.silver.cluster_threshold

    start = target_date - timedelta(days=lookback)
    candidates = archive.clusters_in_window(catalog, start, target_date)
    if not candidates:
        return {}

    published = archive.published_cluster_ids(catalog, start, target_date)
    candidates = [c for c in candidates if c["cluster_id"] in published]
    if not candidates:
        return {}

    story_texts = [_match_text(c.headline, c.summary_seed) for c in contexts]
    candidate_texts = [_match_text(c["headline"], c["summary_seed"]) for c in candidates]

    vectors = cluster.embed([*story_texts, *candidate_texts], model_name)
    story_vecs = vectors[: len(story_texts)]
    candidate_vecs = vectors[len(story_texts) :]
    scores = story_vecs @ candidate_vecs.T

    out: dict[str, list[dict]] = {}
    for i, context in enumerate(contexts):
        matches = [
            (candidates[j], float(scores[i][j]))
            for j in range(len(candidates))
            if float(scores[i][j]) >= threshold
        ]
        if not matches:
            continue
        matches.sort(key=lambda m: (m[0]["ingest_date"], m[1]), reverse=True)
        out[context.cluster_id] = [
            {
                "date": row["ingest_date"].isoformat(),
                "summary": (row["summary_seed"] or row["headline"]).strip(),
                "cluster_id": row["cluster_id"],
            }
            for row, _ in matches
        ]
    return out


def _match_text(headline: str, summary: str | None) -> str:
    """What a story looks like to the matcher: headline plus its summary.

    The body matters. Headline text alone conflates stories that share a
    shape, which is why the headline gate needs story identity as a second
    test rather than relying on text similarity (SPEC 6.5).
    """
    summary = (summary or "").strip()
    return f"{headline}\n{summary}" if summary else headline


def retrieve_prior_mentions(
    context: StoryContext, target_date: date, catalog=None
) -> list[dict]:
    """Earlier editions that covered this story (SPEC 6.5 stage 2).

    The match cannot key on cluster_id: it is sha256(seed_item_id), so the
    same story reported again on a later day gets a different cluster_id.
    Instead the story's text is embedded and matched semantically against
    recently published clusters in gold, reusing the M2 embedding model and
    cluster_threshold over a bounded lookback (SPEC 6.9 archive config).
    Only clusters that were actually published count as prior coverage.

    Without a catalog this returns empty, which is both the M3 behavior and
    what the offline writer-stage tests rely on: the prompt already renders
    a prior-mentions block, so nothing about the writer changes when gold
    starts feeding it (the block is simply no longer always empty).

    One story's slice of `retrieve_prior_mentions_batch`. Prefer the batch
    form when handling more than one story: it shares the gold scan and the
    embedding pass across the whole set.
    """
    return retrieve_prior_mentions_batch([context], target_date, catalog).get(
        context.cluster_id, []
    )
