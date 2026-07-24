"""Background retrieval for the writer stage (SPEC 6.5 stage 2, SPEC 6.9).

retrieve_prior_mentions finds prior *published* coverage of the same story
in gold. cluster_id is not stable across days, so the match is semantic; the
embedding is faked here (as the M2 clustering tests fake it) so the logic
under test is the windowing, the published-only filter, and the threshold,
not the model.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import numpy as np
import pytest

from src import archive, bronze
from src.editor.context import StoryContext, retrieve_prior_mentions
from src.silver import cluster as cluster_mod
from src.silver import table as silver_table
from src.silver.cluster import Cluster
from src.silver.score import ScoringResult

from tests.conftest import make_item

TARGET = date(2026, 7, 20)
NOW = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)

# A toy embedding: same topic keyword -> same unit vector, so a follow-up
# scores cosine 1.0 against its earlier coverage and 0.0 against anything
# else. Above and below the 0.82 threshold with room to spare.
_AXES = {"fed": [1.0, 0.0, 0.0], "apple": [0.0, 1.0, 0.0]}


def _fake_embed(texts, model_name):
    vectors = []
    for text in texts:
        low = text.lower()
        axis = next((v for k, v in _AXES.items() if k in low), [0.0, 0.0, 1.0])
        vectors.append(axis)
    return np.asarray(vectors, dtype=np.float32)


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch):
    monkeypatch.setattr(cluster_mod, "embed", _fake_embed)


def _seed_and_archive(cat, eds, day, headline, *, published: bool, placement="section"):
    """Put one scored cluster into gold for `day`, published or not.

    `placement` picks where a published cluster appears in the edition:
    "section" for a story card, "briefly" for a briefly line, or
    "briefly_legacy" for a briefly line with no cluster_id, which is how
    editions published before decision #23 look.
    """
    eds.mkdir(parents=True, exist_ok=True)
    bt = bronze.ensure_table(cat)
    item = make_item(
        f"https://ex.com/{day.isoformat()}",
        title=headline,
        body="grounding text " * 40,
        published_at=datetime(day.year, day.month, day.day, 9, tzinfo=UTC),
    ).model_copy(update={"ingest_date": day})
    bronze.append_items(bt, [item])

    st = silver_table.ensure_table(cat)
    c = Cluster()
    c.add(item, np.ones(4, dtype="float32"))
    row = silver_table.build_row(
        c,
        ScoringResult(
            score=7,
            rationale="r",
            confidence=0.9,
            topic="Technology",
            model_version="m",
            prompt_version="p",
            scored_at=datetime(day.year, day.month, day.day, 12, tzinfo=UTC),
            cost_usd=0.001,
        ),
    )
    silver_table.overwrite_partition(st, day, [row])

    if published:
        edition = {"edition_number": 1, "edition_type": "normal", "sections": []}
        if placement == "section":
            edition["sections"] = [{"stories": [{"cluster_id": row["cluster_id"]}]}]
        elif placement == "briefly":
            edition["briefly"] = [
                {"cluster_id": row["cluster_id"], "title": headline, "url": "u", "topic": "Tech"}
            ]
        elif placement == "briefly_legacy":
            edition["briefly"] = [{"title": headline, "url": "u", "topic": "Tech"}]
        else:  # pragma: no cover - guards a typo in a test, not a code path
            raise ValueError(f"unknown placement {placement!r}")
        (eds / f"{day.isoformat()}.json").write_text(json.dumps(edition))
    archive.archive_day(cat, day, now=NOW, editions_dir=eds, snapshot_expiry_days=7)
    return row


def _story(headline: str) -> StoryContext:
    return StoryContext(
        cluster_id="today",
        headline=headline,
        summary_seed="a fresh summary",
        topic="Technology",
        score=7,
        rationale=None,
        confidence=0.9,
        member_count=1,
        members=(),
    )


def test_published_follow_up_is_matched(local_catalog, tmp_path):
    cat = local_catalog
    eds = tmp_path / "editions"
    _seed_and_archive(cat, eds, date(2026, 7, 18), "Fed raises interest rates", published=True)

    mentions = retrieve_prior_mentions(_story("Fed holds rates steady"), TARGET, cat)

    assert len(mentions) == 1
    assert mentions[0]["date"] == "2026-07-18"
    assert mentions[0]["summary"]


def test_unpublished_cluster_is_not_a_prior_mention(local_catalog, tmp_path):
    cat = local_catalog
    eds = tmp_path / "editions"
    # In gold and semantically identical, but it never made an edition.
    _seed_and_archive(cat, eds, date(2026, 7, 18), "Fed raises interest rates", published=False)

    mentions = retrieve_prior_mentions(_story("Fed holds rates steady"), TARGET, cat)

    assert mentions == []


def test_unrelated_story_does_not_match(local_catalog, tmp_path):
    cat = local_catalog
    eds = tmp_path / "editions"
    _seed_and_archive(cat, eds, date(2026, 7, 18), "Apple ships a new laptop", published=True)

    mentions = retrieve_prior_mentions(_story("Fed holds rates steady"), TARGET, cat)

    assert mentions == []


def test_coverage_outside_the_lookback_window_is_excluded(local_catalog, tmp_path):
    cat = local_catalog
    eds = tmp_path / "editions"
    # 40 days before the target, beyond the 30-day lookback in pipeline.yaml.
    _seed_and_archive(cat, eds, date(2026, 6, 10), "Fed raises interest rates", published=True)

    mentions = retrieve_prior_mentions(_story("Fed holds rates steady"), TARGET, cat)

    assert mentions == []


def test_briefly_only_coverage_is_a_prior_mention(local_catalog, tmp_path):
    """The 2026-07-22 defect (SPEC 6.9, decision #23).

    That day's top story ran only as a briefly line. Retrieval read section
    cards alone, so the next day's follow-up looked like fresh news and the
    edition led with a near-identical headline two days running.
    """
    cat = local_catalog
    eds = tmp_path / "editions"
    _seed_and_archive(
        cat, eds, date(2026, 7, 18), "Fed raises interest rates",
        published=True, placement="briefly",
    )

    mentions = retrieve_prior_mentions(_story("Fed holds rates steady"), TARGET, cat)

    assert len(mentions) == 1
    assert mentions[0]["date"] == "2026-07-18"


def test_briefly_without_cluster_id_does_not_raise(local_catalog, tmp_path):
    """Editions published before decision #23 have no briefly cluster_id.

    They are the publication record and are never rewritten, so retrieval
    skips them rather than failing on them.
    """
    cat = local_catalog
    eds = tmp_path / "editions"
    _seed_and_archive(
        cat, eds, date(2026, 7, 18), "Fed raises interest rates",
        published=True, placement="briefly_legacy",
    )

    # No cluster_id to match on, so it cannot count as coverage, but the
    # lookup must still complete.
    assert retrieve_prior_mentions(_story("Fed holds rates steady"), TARGET, cat) == []


def test_no_catalog_returns_empty(local_catalog):
    # The M3 / offline-writer-test contract: no gold access, no mentions.
    assert retrieve_prior_mentions(_story("Fed holds rates steady"), TARGET, None) == []
