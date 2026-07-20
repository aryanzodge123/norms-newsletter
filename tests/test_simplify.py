"""The readability revision over editor-owned text (SPEC 6.5).

The gate measures the editor's headline, glance points, and summaries, but
the revision pass used to re-call only the writer stage, so those pieces
could never be fixed. These tests pin the pass that closes that loop.
Offline: Anthropic is stubbed at the client boundary.
"""

from __future__ import annotations

import json

import pytest

from src.config import EditorConfig
from src.editor import simplify

from tests.test_writer_stage import FakeClient

HARD = (
    "The administration's implementation of comprehensive regulatory "
    "modifications necessitated substantial organizational restructuring "
    "throughout numerous governmental departments."
)
EASY = "The new rules made many agencies change how they work."


@pytest.fixture
def config() -> EditorConfig:
    return EditorConfig(
        editor_model="claude-sonnet-4-5-20250929",
        writer_model="claude-haiku-4-5-20251001",
        max_retries=1,
        writer_concurrency=4,
        min_grounding_chars=400,
        min_clusters_for_normal=4,
        min_clusters_for_quiet=2,
    )


def edition_with(headline=EASY, point=EASY, summary=EASY) -> dict:
    return {
        "edition_type": "normal",
        "headline_of_the_day": headline,
        "key_points": [{"text": point, "topic": "Tech"}],
        "sections": [
            {
                "name": "Technology",
                "stories": [
                    {"cluster_id": "a" * 32, "slug": "one", "title": "One",
                     "summary": summary, "score": 7,
                     "sources": [{"name": "hn", "url": "https://x.invalid/a"}],
                     "article": None},
                ],
            }
        ],
    }


# --------------------------------------------------------------------------
# collect_failing
# --------------------------------------------------------------------------
def test_collects_only_the_hard_lines() -> None:
    failing = simplify.collect_failing(edition_with(headline=HARD, point=EASY, summary=HARD))
    ids = {p["id"] for p in failing}
    assert ids == {"headline", "summary:one"}


def test_nothing_to_do_on_a_plain_edition() -> None:
    assert simplify.collect_failing(edition_with()) == []


def test_hardest_first() -> None:
    failing = simplify.collect_failing(edition_with(headline=HARD, point=HARD, summary=HARD))
    grades = [simplify.readability.grade(p["text"]) for p in failing]
    assert grades == sorted(grades, reverse=True)


def test_summary_is_keyed_by_slug() -> None:
    failing = simplify.collect_failing(edition_with(summary=HARD))
    assert any(p["id"] == "summary:one" for p in failing)


# --------------------------------------------------------------------------
# apply_rewrites
# --------------------------------------------------------------------------
def test_rewrites_land_in_the_right_places() -> None:
    edition = edition_with(headline=HARD, point=HARD, summary=HARD)
    applied = simplify.apply_rewrites(
        edition,
        {"headline": "A short headline.", "point:0": "A short point.", "summary:one": "A short summary."},
    )
    assert applied == 3
    assert edition["headline_of_the_day"] == "A short headline."
    assert edition["key_points"][0]["text"] == "A short point."
    assert edition["sections"][0]["stories"][0]["summary"] == "A short summary."


def test_rewrites_do_not_touch_structure() -> None:
    """Curation is decided before this pass and must survive it: the model
    returns prose keyed by id and never sees ordering, topics, or slugs."""
    edition = edition_with(summary=HARD)
    before_topic = edition["key_points"][0]["topic"]
    simplify.apply_rewrites(edition, {"summary:one": "Short."})
    assert edition["key_points"][0]["topic"] == before_topic
    assert edition["sections"][0]["stories"][0]["slug"] == "one"
    assert edition["sections"][0]["stories"][0]["score"] == 7


def test_unknown_ids_are_ignored() -> None:
    edition = edition_with()
    assert simplify.apply_rewrites(edition, {"summary:nope": "x", "point:99": "y"}) == 0


# --------------------------------------------------------------------------
# simplify_edition
# --------------------------------------------------------------------------
def test_simplifies_a_hard_edition(config) -> None:
    edition = edition_with(headline=HARD, summary=HARD)
    reply = json.dumps({"items": [
        {"id": "headline", "text": EASY},
        {"id": "summary:one", "text": EASY},
    ]})
    applied, cost = simplify.simplify_edition(FakeClient([reply]), edition, config, "sys")
    assert applied == 2
    assert edition["headline_of_the_day"] == EASY
    assert cost > 0


def test_no_call_when_everything_reads_plainly(config) -> None:
    client = FakeClient([])
    applied, cost = simplify.simplify_edition(client, edition_with(), config, "sys")
    assert (applied, cost) == (0, 0.0)
    assert client.messages.calls == 0


def test_a_rewrite_that_reads_harder_is_rejected(config) -> None:
    """A "simplification" that grades worse than the original is not one."""
    edition = edition_with(headline=HARD)
    # One longer sentence with denser words: grade 42.8 against the original
    # 34.3. Note that merely appending a short sentence would *lower* the
    # grade, since the formula averages words per sentence.
    harder = (
        "The administration comprehensively implemented extraordinarily complicated "
        "regulatory modifications which subsequently necessitated substantially "
        "unprecedented organizational restructuring initiatives throughout innumerable "
        "governmental administrative departments and interdepartmental subdivisions nationwide."
    )
    reply = json.dumps({"items": [{"id": "headline", "text": harder}]})
    applied, _ = simplify.simplify_edition(FakeClient([reply]), edition, config, "sys")
    assert applied == 0
    assert edition["headline_of_the_day"] == HARD


def test_ids_we_did_not_ask_about_are_ignored(config) -> None:
    edition = edition_with(headline=HARD)
    reply = json.dumps({"items": [
        {"id": "headline", "text": EASY},
        {"id": "summary:one", "text": "The editor did not ask about this."},
    ]})
    applied, _ = simplify.simplify_edition(FakeClient([reply]), edition, config, "sys")
    assert applied == 1
    assert edition["sections"][0]["stories"][0]["summary"] == EASY  # unchanged


def test_failure_keeps_the_original_text(config) -> None:
    """An AI failure here is contained like every other one in this stage:
    the edition keeps its text and publishes flagged."""
    edition = edition_with(headline=HARD)
    client = FakeClient(["not json", "still not json"])
    applied, _ = simplify.simplify_edition(client, edition, config, "sys")
    assert applied == 0
    assert edition["headline_of_the_day"] == HARD


def test_em_dash_is_rejected(config) -> None:
    edition = edition_with(headline=HARD)
    bad = json.dumps({"items": [{"id": "headline", "text": "A line with an em dash — here."}]})
    client = FakeClient([bad, bad])
    applied, _ = simplify.simplify_edition(client, edition, config, "sys")
    assert applied == 0
