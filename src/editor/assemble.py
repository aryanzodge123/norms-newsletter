"""Assemble the final edition.json from the pieces (SPEC 6.5).

The editor call returns curation. The writer stage returns articles. This
module joins them to the deterministic facts the pipeline owns (slugs,
scores, source URLs, stats, edition_number) and produces an object that
schema.validate_edition accepts. It also builds the fallback edition, which
takes no editor output at all.

Nothing here calls a model. This is the deterministic seam between the two
AI stages and the validated artifact.
"""

from __future__ import annotations

import logging
from datetime import date

from .context import StoryContext
from .plan import build_stats, next_edition_number, unique_slugs
from .run_writers import ArticleResult
from .schema import (
    FALLBACK_STORIES,
    MIN_STORIES_PER_SECTION,
    SECTION_NAMES,
    SECTION_ORDER,
    EditorResponse,
    validate_edition,
)

log = logging.getLogger(__name__)


def _briefly_items(
    briefly_ids: list[str], by_id: dict[str, StoryContext], used: set[str]
) -> list[dict]:
    """Resolve the editor's briefly cluster ids to {cluster_id, title, url, topic}.

    Ids that are unknown, that name a story already placed in a section, or
    that carry no section topic are dropped. The editor works from cluster
    ids and the renderer needs URLs, so this is where the two meet.

    The cluster_id is carried through rather than consumed here: briefly is
    published coverage, and gold retrieval can only find it again if the
    edition records which cluster it was (SPEC 6.9, decision #23).
    """
    items: list[dict] = []
    seen: set[str] = set()
    for cluster_id in briefly_ids:
        context = by_id.get(cluster_id)
        if context is None or cluster_id in used or cluster_id in seen:
            continue
        if context.topic not in SECTION_NAMES:
            continue
        seen.add(cluster_id)
        items.append(
            {
                "cluster_id": cluster_id,
                "title": context.headline,
                "url": context.primary_url,
                "topic": context.topic,
            }
        )
    return items


def assemble_edition(
    *,
    editor: EditorResponse,
    articles: dict[str, ArticleResult],
    contexts: list[StoryContext],
    edition_type: str,
    target_date: date,
    items_ingested: int,
    clusters_considered: int,
    sections_held: int,
    editions_dir=None,
) -> dict:
    """Build and validate a normal or quiet edition.

    Raises schema.EditionInvalid if the assembled object does not conform,
    which is the caller's signal to fall back. The editor's output already
    validated against EditorResponse, so a failure here is an assembly bug
    or an editor that selected a cluster it was not offered.
    """
    by_id = {context.cluster_id: context for context in contexts}

    # SPEC 6.5: "Dead sections collapse into briefly". A section the editor
    # under-filled cannot meet the min-2 budget, so its stories move to
    # briefly rather than costing the whole edition a fallback. This is code,
    # not a model instruction, because the API's structured-output subset
    # cannot express "at least 2 items" (it rejects minItems above 1).
    kept_sections = []
    spilled_to_briefly: list[str] = []
    for section in editor.sections:
        known = section.name in SECTION_ORDER
        if known and len(section.stories) >= MIN_STORIES_PER_SECTION:
            kept_sections.append(section)
            continue
        # Unknown name (the model sometimes invents one, including a literal
        # "briefly" section) or too few stories to meet the budget. Either
        # way the stories move to briefly rather than costing the edition.
        spilled_to_briefly.extend(story.cluster_id for story in section.stories)
        log.info(
            "dropping section %r (%s, %d stories), moving them to briefly (SPEC 6.5)",
            section.name,
            "known" if known else "unknown name",
            len(section.stories),
        )

    # Slugs are assigned across the whole edition at once so collisions are
    # resolved deterministically in story order (plan.unique_slugs).
    ordered: list[tuple[str, str, str, StoryContext]] = []  # section, title, summary, ctx
    for section in kept_sections:
        for story in section.stories:
            context = by_id.get(story.cluster_id)
            if context is None:
                raise _invalid(
                    f"editor selected cluster {story.cluster_id!r} which was not offered"
                )
            ordered.append((section.name, story.title, story.summary, context))

    slugs = unique_slugs([title for _, title, _, _ in ordered])

    stories_by_section: dict[str, list[dict]] = {}
    used_clusters: set[str] = set()
    for (section_name, title, summary, context), slug in zip(ordered, slugs):
        used_clusters.add(context.cluster_id)
        result = articles.get(context.cluster_id)
        article = result.article if result is not None else None
        stories_by_section.setdefault(section_name, []).append(
            {
                "cluster_id": context.cluster_id,
                "slug": slug,
                "title": title,
                "summary": summary,
                # The score is the pipeline's, not the editor's (rule zero).
                "score": context.score,
                "sources": context.sources,
                "article": article,
            }
        )

    sections = [
        {"name": name, "stories": stories_by_section[name]}
        for name in SECTION_ORDER
        if name in stories_by_section
    ]

    stories_run = sum(len(section["stories"]) for section in sections)
    edition = {
        "date": target_date.isoformat(),
        "edition_number": next_edition_number(target_date, editions_dir),
        "edition_type": edition_type,
        "headline_of_the_day": editor.headline_of_the_day,
        "key_points": [point.model_dump() for point in editor.key_points],
        "audio": None,  # M6 fills this in; nullable per SPEC 6.5.
        "sections": sections,
        # Spilled stories lead the briefly list: they were good enough for a
        # section, so they outrank what the editor already relegated.
        "briefly": _briefly_items(
            spilled_to_briefly + list(editor.briefly), by_id, used_clusters
        ),
        "stats": build_stats(
            items_ingested=items_ingested,
            clusters_considered=clusters_considered,
            stories_run=stories_run,
            contexts=contexts,
            sections_held=sections_held,
        ),
    }

    validate_edition(edition)
    return edition


def assemble_fallback(
    *,
    contexts: list[StoryContext],
    target_date: date,
    notice: str,
    editions_dir=None,
) -> dict:
    """SPEC section 7's abbreviated edition (decision #8).

    Top ten usable clusters by score, titles and links only. Built from the
    same contexts the editor would have seen, so a total editor failure
    still yields a real, ranked page rather than a blank one. Contexts
    arrive already sorted by score (context.build_contexts).
    """
    ranked = contexts[:FALLBACK_STORIES]
    stories = [
        {
            "rank": index + 1,
            "title": context.headline,
            "score": context.score,
            "url": context.primary_url,
            "source": context.primary_source,
        }
        for index, context in enumerate(ranked)
    ]
    edition = {
        "date": target_date.isoformat(),
        "edition_number": next_edition_number(target_date, editions_dir),
        "edition_type": "fallback",
        "notice": notice,
        "stories": stories,
    }
    validate_edition(edition)
    return edition


def _invalid(message: str):
    from .schema import EditionInvalid

    return EditionInvalid(message)
