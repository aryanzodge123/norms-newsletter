"""The headline repetition gate (SPEC 6.5).

Editions 45 and 46 both led with the OpenAI / Hugging Face story under
near-identical headlines. Leading with a developing story twice is allowed
and often right; restating yesterday's sentence is not.

Two design choices are worth stating, because both were arrived at by
measurement rather than by reasoning.

**It reads the committed editions, not gold.** `site/content/editions/` is
the publication record (decision #17) and `plan.next_edition_number` already
treats it that way. Reading disk means the gate needs no catalog, so it
works offline and costs no R2 round trip.

**It fires on a conjunction, not on text alone.** The embedding captures a
headline's shape and topic rather than its event: measured on the pinned
model, "judge blocks a merger" and "judge approves a merger" score 0.836,
and two tariff headlines about different countries score 0.844. Text alone
would block legitimate headlines, because news runs on recurring templates.
So the gate also requires that the story behind today's headline is
continuing coverage of the story behind the earlier one. That evidence is
already computed for the editor prompt, so the second test is free.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from ..config import REPO_ROOT

log = logging.getLogger(__name__)

EDITIONS_DIR = REPO_ROOT / "site" / "content" / "editions"


@dataclass(frozen=True)
class PriorHeadline:
    """One earlier edition's headline, and the story it led with."""

    date: str
    headline: str
    cluster_id: str | None


@dataclass(frozen=True)
class GateResult:
    """Whether the gate fired, and what it fired against."""

    repeated: bool
    prior: PriorHeadline | None = None
    similarity: float = 0.0

    def feedback(self) -> str:
        """What the editor is told on the retry.

        Names the offending headline and asks for the new development,
        rather than just reporting a rejection: the editor may still lead
        with this story (SPEC 6.5).
        """
        assert self.prior is not None
        return (
            f"Your headline repeats the one published on {self.prior.date}: "
            f'"{self.prior.headline}". That edition already told the reader '
            "that story, so this headline gives them nothing new.\n"
            "You may still lead with this story if it is the most important "
            "thing that happened. If you do, the headline must name what is "
            "new today, the development that made it news again, not the "
            "event the earlier edition already reported."
        )


def recent_headlines(
    target_date: date,
    lookback_days: int,
    editions_dir: Path | None = None,
) -> list[PriorHeadline]:
    """Headlines published in [target_date - lookback, target_date).

    The window is end-exclusive so a re-run of an already-published date
    never compares an edition against its own headline. Fallback editions
    are skipped: they carry no `headline_of_the_day` at all (SPEC 6.5).
    """
    editions_dir = editions_dir if editions_dir is not None else EDITIONS_DIR
    if not editions_dir.is_dir():
        return []

    start = target_date - timedelta(days=lookback_days)
    out: list[PriorHeadline] = []
    for path in sorted(editions_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("skipping unreadable edition %s: %s", path.name, exc)
            continue
        raw_date = payload.get("date")
        if not isinstance(raw_date, str):
            continue
        try:
            day = date.fromisoformat(raw_date)
        except ValueError:
            continue
        if not (start <= day < target_date):
            continue
        headline = payload.get("headline_of_the_day")
        if not isinstance(headline, str) or not headline.strip():
            # A fallback edition, which has no headline of the day.
            continue
        out.append(
            PriorHeadline(
                date=raw_date,
                headline=headline.strip(),
                cluster_id=payload.get("headline_cluster_id"),
            )
        )
    return out


def check(
    headline: str,
    prior: list[PriorHeadline],
    *,
    threshold: float,
    model_name: str,
    prior_coverage: list[dict] | None = None,
) -> GateResult:
    """Does `headline` restate one of `prior`?

    Fires only when both halves hold:

    1. the text is at or above `threshold` against an earlier headline, and
    2. `prior_coverage` shows the story behind this headline is continuing
       coverage, and covers the day that earlier headline was published.

    `prior_coverage` is this story's slice of the edition-wide map from
    `context.retrieve_prior_mentions_batch`. Empty or None means the story
    is not continuing anything, so no amount of text similarity fires: a
    headline that merely rhymes with last week's is not a repeat.
    """
    if not headline.strip() or not prior:
        return GateResult(False)

    covered_days = {m.get("date") for m in (prior_coverage or [])}
    if not covered_days:
        return GateResult(False)

    # Only earlier headlines whose day this story actually continues can be
    # repeated. This is what stops a structurally similar but unrelated
    # headline from firing the gate.
    candidates = [p for p in prior if p.date in covered_days]
    if not candidates:
        return GateResult(False)

    from ..silver import cluster

    vectors = cluster.embed([headline.strip(), *[p.headline for p in candidates]], model_name)
    query = vectors[0]
    scores = vectors[1:] @ query

    best_i = int(max(range(len(candidates)), key=lambda i: float(scores[i])))
    best = float(scores[best_i])
    if best >= threshold:
        return GateResult(True, candidates[best_i], best)
    return GateResult(False, candidates[best_i], best)
