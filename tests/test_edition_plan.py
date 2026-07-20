"""Deterministic structural decisions (SPEC 6.5, rule zero).

Edition type, edition number, slugs, and the section budget are decided in
code before any AI call, so they are tested without one.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from src.config import EditorConfig
from src.editor import plan
from src.editor.context import StoryContext

from tests.conftest import make_item


def make_context(cluster_id: str, *, topic="Tech", score=5, members=None) -> StoryContext:
    members = members or (make_item(f"https://x.invalid/{cluster_id}"),)
    return StoryContext(
        cluster_id=cluster_id,
        headline=f"Headline {cluster_id}",
        summary_seed="Seed text.",
        topic=topic,
        score=score,
        rationale="because",
        confidence=0.7,
        member_count=len(members),
        members=tuple(members),
    )


@pytest.fixture
def config() -> EditorConfig:
    return EditorConfig(
        editor_model="claude-sonnet-4-5-20250929",
        writer_model="claude-haiku-4-5-20251001",
        max_retries=1,
        writer_concurrency=6,
        min_clusters_for_normal=12,
        min_clusters_for_quiet=3,
        min_grounding_chars=400,
    )


# --------------------------------------------------------------------------
# slugify / unique_slugs
# --------------------------------------------------------------------------
def test_slugify_is_deterministic_and_clean():
    assert plan.slugify("Hello, World!") == "hello-world"
    assert plan.slugify("  Spaces   and--dashes  ") == "spaces-and-dashes"


def test_slugify_truncates_on_word_boundary():
    title = "This is an exceptionally long headline that keeps going well beyond the limit"
    slug = plan.slugify(title)
    assert len(slug) <= plan.SLUG_MAX_CHARS
    assert not slug.endswith("-")
    assert "-" in slug  # did not cut mid-word to nothing


def test_slugify_empty_falls_back():
    assert plan.slugify("!!!") == "story"


def test_unique_slugs_disambiguates_collisions():
    slugs = plan.unique_slugs(["Same Title", "Same Title", "Other"])
    assert slugs == ["same-title", "same-title-2", "other"]


# --------------------------------------------------------------------------
# next_edition_number (decision #17)
# --------------------------------------------------------------------------
def test_edition_number_is_one_when_no_history(tmp_path):
    assert plan.next_edition_number(date(2026, 7, 20), tmp_path) == 1


def test_edition_number_increments_past_the_max(tmp_path):
    (tmp_path / "2026-07-18.json").write_text(json.dumps({"date": "2026-07-18", "edition_number": 5}))
    (tmp_path / "2026-07-19.json").write_text(json.dumps({"date": "2026-07-19", "edition_number": 6}))
    assert plan.next_edition_number(date(2026, 7, 20), tmp_path) == 7


def test_rerun_of_existing_date_reuses_its_number(tmp_path):
    (tmp_path / "2026-07-18.json").write_text(json.dumps({"date": "2026-07-18", "edition_number": 5}))
    (tmp_path / "2026-07-19.json").write_text(json.dumps({"date": "2026-07-19", "edition_number": 6}))
    assert plan.next_edition_number(date(2026, 7, 18), tmp_path) == 5


def test_unreadable_edition_file_is_skipped(tmp_path):
    (tmp_path / "2026-07-18.json").write_text(json.dumps({"date": "2026-07-18", "edition_number": 5}))
    (tmp_path / "broken.json").write_text("{not valid json")
    assert plan.next_edition_number(date(2026, 7, 20), tmp_path) == 6


# --------------------------------------------------------------------------
# choose_edition_type
# --------------------------------------------------------------------------
def test_normal_at_threshold(config):
    contexts = [make_context(f"{i:032d}") for i in range(config.min_clusters_for_normal)]
    assert plan.choose_edition_type(contexts, config) == "normal"


def test_quiet_just_below_normal(config):
    contexts = [make_context(f"{i:032d}") for i in range(config.min_clusters_for_normal - 1)]
    assert plan.choose_edition_type(contexts, config) == "quiet"


def test_quiet_at_its_own_threshold(config):
    contexts = [make_context(f"{i:032d}") for i in range(config.min_clusters_for_quiet)]
    assert plan.choose_edition_type(contexts, config) == "quiet"


def test_fallback_below_quiet(config):
    contexts = [make_context(f"{i:032d}") for i in range(config.min_clusters_for_quiet - 1)]
    assert plan.choose_edition_type(contexts, config) == "fallback"


def test_fallback_on_empty(config):
    assert plan.choose_edition_type([], config) == "fallback"


# --------------------------------------------------------------------------
# plan_sections: the min-2 rule (SPEC 6.5)
# --------------------------------------------------------------------------
def test_section_needs_two_stories_to_run():
    contexts = [
        make_context("a" * 32, topic="Tech"),
        make_context("b" * 32, topic="Tech"),
        make_context("c" * 32, topic="Science"),  # only one
    ]
    result = plan.plan_sections(contexts)
    assert "Technology" in result.available
    assert "Science" in result.held
    assert "Science" not in result.available


def test_three_dead_sections_shrink_the_edition():
    contexts = [
        make_context("a" * 32, topic="Tech"),
        make_context("b" * 32, topic="Tech"),
        make_context("c" * 32, topic="Science"),
        make_context("d" * 32, topic="Finance"),
        make_context("e" * 32, topic="World"),
    ]
    result = plan.plan_sections(contexts)
    assert result.shrink is True
    assert set(result.held) == {"Science", "Finance", "World"}


# --------------------------------------------------------------------------
# build_stats
# --------------------------------------------------------------------------
def test_build_stats_counts_distinct_sources():
    contexts = [
        make_context("a" * 32, members=(
            make_item("https://x.invalid/1", source="hackernews"),
            make_item("https://x.invalid/2", source="arstechnica"),
        )),
        make_context("b" * 32, members=(make_item("https://x.invalid/3", source="hackernews"),)),
    ]
    stats = plan.build_stats(
        items_ingested=100,
        clusters_considered=40,
        stories_run=2,
        contexts=contexts,
        sections_held=1,
    )
    assert stats == {
        "items_ingested": 100,
        "clusters_considered": 40,
        "stories_run": 2,
        "sources": 2,  # hackernews, arstechnica
        "sections_held": 1,
    }
