"""Structural decisions, made in code before any AI call (SPEC 6.5).

Rule zero draws the line here. What kind of edition today is, what number
it carries, what each story's permanent anchor is, and what the stats say
are all facts the pipeline already knows. None of them are asked of a
model. The editor agent is told which mode it is writing and curates
within it.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..config import REPO_ROOT, EditorConfig
from .context import StoryContext
from .schema import SECTION_NAMES, TOPICS

log = logging.getLogger(__name__)

EDITIONS_DIR = REPO_ROOT / "site" / "content" / "editions"

SLUG_MAX_CHARS = 60
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(title: str) -> str:
    """A story's permanent anchor (DESIGN.md StoryCard `id={slug}`).

    Deterministic and code-owned because it is a URL fragment that other
    pages deep-link to. Truncated on a word boundary so a slug never ends
    mid-word.
    """
    cleaned = _NON_SLUG.sub("-", title.casefold()).strip("-")
    if len(cleaned) <= SLUG_MAX_CHARS:
        return cleaned or "story"
    cut = cleaned[:SLUG_MAX_CHARS]
    if "-" in cut:
        cut = cut.rsplit("-", 1)[0]
    return cut.strip("-") or "story"


def unique_slugs(titles: list[str]) -> list[str]:
    """Slugs for one edition, disambiguated in order.

    Collisions get -2, -3 and so on. Order matters and is the edition's own
    story order, so the same edition always produces the same slugs.
    """
    counts: dict[str, int] = {}
    out: list[str] = []
    for title in titles:
        base = slugify(title)
        counts[base] = counts.get(base, 0) + 1
        out.append(base if counts[base] == 1 else f"{base}-{counts[base]}")
    return out


def next_edition_number(target_date: date, editions_dir: Path | None = None) -> int:
    """The edition number for a given date.

    Derived from the publication record itself (decision #17: the editions
    committed to the repo are the record), so the number cannot drift from
    what is on disk. Re-running a date that already published reuses that
    date's number rather than incrementing, which is what makes a re-run a
    correction instead of a new edition.
    """
    editions_dir = editions_dir if editions_dir is not None else EDITIONS_DIR
    if not editions_dir.is_dir():
        return 1

    existing: dict[str, int] = {}
    for path in sorted(editions_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("skipping unreadable edition %s: %s", path.name, exc)
            continue
        day, number = payload.get("date"), payload.get("edition_number")
        if isinstance(day, str) and isinstance(number, int):
            existing[day] = number

    iso = target_date.isoformat()
    if iso in existing:
        log.info("edition for %s already exists as No. %d, reusing", iso, existing[iso])
        return existing[iso]
    return max(existing.values(), default=0) + 1


def choose_edition_type(contexts: list[StoryContext], config: EditorConfig) -> str:
    """normal, quiet, or fallback, decided from configured thresholds.

    SPEC 6.5 says a "broadly quiet day" produces a quiet edition and
    section 7 says "zero/near-zero data" does too, without quantifying
    either. The numbers live in config/pipeline.yaml so tuning them is a
    config change, and the decision lives here so it is deterministic and
    testable without an API call.

    Note the third case is not a *failure* fallback. Section 7's fallback
    is normally the editor-invalid-twice path. A day with almost no data
    lands here too, because a fallback edition is what an abbreviated day
    looks like (decision #8: never skip a day silently).
    """
    usable = len(contexts)
    if usable >= config.min_clusters_for_normal:
        return "normal"
    if usable >= config.min_clusters_for_quiet:
        log.info(
            "quiet edition: %d usable clusters, below the %d needed for normal",
            usable,
            config.min_clusters_for_normal,
        )
        return "quiet"
    log.warning(
        "fallback edition: %d usable clusters, below the %d needed for quiet",
        usable,
        config.min_clusters_for_quiet,
    )
    return "fallback"


@dataclass(frozen=True)
class SectionPlan:
    """Which topics can field a section, and which are held.

    SPEC 6.5: min 2 per section, dead sections collapse into briefly, 3+
    dead sections shrink the edition. Computing this before the editor
    call means the prompt is told which sections are available instead of
    being trusted to work out the budget itself.
    """

    available: tuple[str, ...]
    held: tuple[str, ...]

    @property
    def shrink(self) -> bool:
        """SPEC 6.5: "3+ dead sections -> shrink the edition"."""
        return len(self.held) >= 3


def plan_sections(contexts: list[StoryContext]) -> SectionPlan:
    """Group by topic and apply the min-2 rule.

    A topic with only one usable story cannot be a section, so it is held
    and its story goes to briefly. Topics with no stories at all are not
    "held" in the DESIGN.md Sidebar sense: nothing was withheld, there was
    simply nothing there. Only topics that had stories but too few count.
    """
    counts: dict[str, int] = {}
    for context in contexts:
        if context.topic in SECTION_NAMES:
            counts[context.topic] = counts.get(context.topic, 0) + 1

    available = tuple(
        SECTION_NAMES[topic] for topic in TOPICS if counts.get(topic, 0) >= 2
    )
    held = tuple(SECTION_NAMES[topic] for topic in TOPICS if counts.get(topic, 0) == 1)
    return SectionPlan(available=available, held=held)


def build_stats(
    *,
    items_ingested: int,
    clusters_considered: int,
    stories_run: int,
    contexts: list[StoryContext],
    sections_held: int,
) -> dict:
    """The Sidebar's "By the numbers" box (DESIGN.md Sidebar, SPEC 6.5).

    Every field is counted, never generated. `sources` is distinct source
    names across the whole day's usable clusters, which is the honest read
    of "how many places did today's brief draw on".
    """
    sources = {member.source for context in contexts for member in context.members}
    return {
        "items_ingested": items_ingested,
        "clusters_considered": clusters_considered,
        "stories_run": stories_run,
        "sources": len(sources),
        "sections_held": sections_held,
    }
