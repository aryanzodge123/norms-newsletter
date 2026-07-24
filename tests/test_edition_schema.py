"""The edition schema is the authority on a valid edition (SPEC 6.5).

Every constraint SPEC 6.5 states in prose is asserted here by rejection,
because a constraint that is only in the prompt is a constraint that is not
enforced. The fixtures are also validated here, so a broken fixture fails
in pytest rather than only in the milestone gate.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.editor import schema
from src.editor.schema import EditionInvalid, validate_edition

FIXTURES = Path(__file__).resolve().parents[1] / "site" / "fixtures"


@pytest.fixture
def normal() -> dict:
    return json.loads((FIXTURES / "normal.json").read_text())


@pytest.fixture
def quiet() -> dict:
    return json.loads((FIXTURES / "quiet.json").read_text())


@pytest.fixture
def fallback() -> dict:
    return json.loads((FIXTURES / "fallback.json").read_text())


# --------------------------------------------------------------------------
# Fixtures validate. This is the gate's check 2, kept here to fail fast.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["normal", "quiet", "fallback"])
def test_fixture_validates(name):
    obj = json.loads((FIXTURES / f"{name}.json").read_text())
    validate_edition(obj)


def test_all_three_edition_types_exist_as_fixtures():
    for name in ("normal", "quiet", "fallback"):
        assert (FIXTURES / f"{name}.json").exists(), f"missing {name}.json (DESIGN 5)"


# --------------------------------------------------------------------------
# Dispatch and top-level shape
# --------------------------------------------------------------------------
def test_unknown_edition_type_rejected(normal):
    normal["edition_type"] = "special"
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_non_object_rejected():
    with pytest.raises(EditionInvalid):
        validate_edition(["not", "an", "object"])


def test_unknown_top_level_key_rejected(normal):
    normal["surprise"] = True
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_bad_date_rejected(normal):
    normal["date"] = "19-07-2026"
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_edition_number_must_be_positive(normal):
    normal["edition_number"] = 0
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


# --------------------------------------------------------------------------
# Key points: 4-6 normal, 3 quiet (SPEC 6.5)
# --------------------------------------------------------------------------
def test_normal_key_points_lower_bound(normal):
    normal["key_points"] = normal["key_points"][:3]
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_normal_key_points_upper_bound(normal):
    extra = dict(normal["key_points"][0])
    normal["key_points"] = normal["key_points"] + [extra, extra]  # 7
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_normal_accepts_four_to_six_points(normal):
    normal["key_points"] = normal["key_points"][:4]
    validate_edition(normal)


def test_quiet_requires_exactly_three_points(quiet):
    quiet["key_points"] = quiet["key_points"][:2]
    with pytest.raises(EditionInvalid):
        validate_edition(quiet)


def test_unknown_key_point_topic_rejected(normal):
    normal["key_points"][0]["topic"] = "Weather"
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


# --------------------------------------------------------------------------
# The 'norm' key point: quiet only, at most one (SPEC 6.5)
# --------------------------------------------------------------------------
def test_norm_point_rejected_on_normal(normal):
    normal["key_points"][0]["topic"] = "norm"
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_quiet_allows_one_norm_point(quiet):
    assert any(p["topic"] == "norm" for p in quiet["key_points"])
    validate_edition(quiet)


def test_quiet_rejects_two_norm_points(quiet):
    quiet["key_points"][0]["topic"] = "norm"  # now two
    with pytest.raises(EditionInvalid):
        validate_edition(quiet)


# --------------------------------------------------------------------------
# Sections: skeleton names, order, per-section 2-4 (SPEC 6.5)
# --------------------------------------------------------------------------
def test_unknown_section_name_rejected(normal):
    normal["sections"][0]["name"] = "Sports"
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_section_with_one_story_rejected(normal):
    normal["sections"][0]["stories"] = normal["sections"][0]["stories"][:1]
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_section_with_five_stories_rejected(normal):
    section = normal["sections"][0]
    story = copy.deepcopy(section["stories"][0])
    # give each a distinct slug and cluster_id so only the count is at fault
    while len(section["stories"]) < 5:
        clone = copy.deepcopy(story)
        n = len(section["stories"])
        clone["slug"] = f"{story['slug']}-{n}"
        clone["cluster_id"] = story["cluster_id"][:-1] + str(n)
        section["stories"].append(clone)
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_sections_must_follow_skeleton_order(normal):
    normal["sections"] = list(reversed(normal["sections"]))
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_duplicate_section_rejected(normal):
    normal["sections"].append(copy.deepcopy(normal["sections"][0]))
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


# --------------------------------------------------------------------------
# Stories: budget ceiling, unique slugs, unique clusters
# --------------------------------------------------------------------------
def test_story_ceiling_enforced(normal):
    # 21 stories across valid, in-order sections of 4 (well over 20) so the
    # ceiling is the only rule that can fire, not the per-section bound.
    template = copy.deepcopy(normal["sections"][0]["stories"][0])
    template["article"] = None
    counter = 0

    def story():
        nonlocal counter
        clone = copy.deepcopy(template)
        clone["slug"] = f"filler-{counter}"
        clone["cluster_id"] = f"{counter:032d}"
        clone["title"] = f"Filler story number {counter}"
        counter += 1
        return clone

    # SECTION_ORDER has nine names; six sections of four is 24 stories.
    normal["sections"] = [
        {"name": name, "stories": [story() for _ in range(4)]}
        for name in schema.SECTION_ORDER[:6]
    ]
    assert sum(len(s["stories"]) for s in normal["sections"]) > schema.MAX_STORIES
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_duplicate_slug_rejected(normal):
    normal["sections"][0]["stories"][1]["slug"] = normal["sections"][0]["stories"][0]["slug"]
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_duplicate_cluster_rejected(normal):
    a = normal["sections"][0]["stories"][0]["cluster_id"]
    normal["sections"][1]["stories"][0]["cluster_id"] = a
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_score_out_of_range_rejected(normal):
    normal["sections"][0]["stories"][0]["score"] = 11
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


# --------------------------------------------------------------------------
# Nullable and optional fields (SPEC 6.5 notes)
# --------------------------------------------------------------------------
def test_null_audio_allowed(normal):
    normal["audio"] = None
    validate_edition(normal)


def test_null_article_allowed(normal):
    # normal.json already ships one collapsed card; assert it validates and
    # that its story has no article.
    ed = validate_edition(normal)
    collapsed = [s for section in ed.sections for s in section.stories if s.article is None]
    assert collapsed, "fixture should include at least one collapsed card"


def test_absent_quote_allowed(normal):
    for section in normal["sections"]:
        for story in section["stories"]:
            if story.get("article"):
                story["article"]["quote"] = None
    validate_edition(normal)


# --------------------------------------------------------------------------
# Quote policy (decision #15)
# --------------------------------------------------------------------------
def _story_with_quote(normal) -> dict:
    for section in normal["sections"]:
        for story in section["stories"]:
            if story.get("article") and story["article"].get("quote"):
                return story
    raise AssertionError("fixture has no quote to mutate")


def test_quote_source_url_must_be_a_story_source(normal):
    story = _story_with_quote(normal)
    story["article"]["quote"]["source_url"] = "https://elsewhere.invalid/not-cited"
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_over_long_quote_rejected(normal):
    story = _story_with_quote(normal)
    story["article"]["quote"]["text"] = "word " * 100
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


# --------------------------------------------------------------------------
# Em dash ban (CLAUDE.md rule 7, voice standard 8)
# --------------------------------------------------------------------------
def test_em_dash_in_summary_rejected(normal):
    normal["sections"][0]["stories"][0]["summary"] = "A thing happened — and it mattered."
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_em_dash_in_headline_rejected(normal):
    normal["headline_of_the_day"] = "Big news — today"
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


# --------------------------------------------------------------------------
# Briefly does not repeat section stories (SPEC 6.5)
# --------------------------------------------------------------------------
def test_briefly_cannot_repeat_a_section_story(normal):
    title = normal["sections"][0]["stories"][0]["title"]
    normal["briefly"].append(
        {
            "cluster_id": "9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f",
            "title": title,
            "url": "https://x.invalid/a",
            "topic": "Tech",
        }
    )
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_unknown_briefly_topic_rejected(normal):
    normal["briefly"][0]["topic"] = "norm"  # norm allowed in key_points, not briefly
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


def test_briefly_without_a_cluster_id_rejected(normal):
    """Briefly is published coverage, so it has to name its cluster.

    Without the id, gold retrieval cannot find the story again and a
    briefly-only item comes back the next day as if it were new
    (SPEC 6.5, 6.9, decision #23).
    """
    del normal["briefly"][0]["cluster_id"]
    with pytest.raises(EditionInvalid):
        validate_edition(normal)


# --------------------------------------------------------------------------
# Fallback shape (SPEC 6.5, section 7)
# --------------------------------------------------------------------------
def test_fallback_rejects_more_than_ten(fallback):
    extra = dict(fallback["stories"][-1])
    extra["rank"] = 11
    fallback["stories"].append(extra)
    with pytest.raises(EditionInvalid):
        validate_edition(fallback)


def test_fallback_ranks_must_be_contiguous(fallback):
    fallback["stories"][0]["rank"] = 5
    with pytest.raises(EditionInvalid):
        validate_edition(fallback)


def test_fallback_must_be_ordered_by_score(fallback):
    fallback["stories"][0]["score"] = 1  # now lower than rank 2
    with pytest.raises(EditionInvalid):
        validate_edition(fallback)


def test_fallback_rejects_section_fields(fallback):
    fallback["sections"] = []
    with pytest.raises(EditionInvalid):
        validate_edition(fallback)


def test_fallback_needs_a_notice(fallback):
    del fallback["notice"]
    with pytest.raises(EditionInvalid):
        validate_edition(fallback)
