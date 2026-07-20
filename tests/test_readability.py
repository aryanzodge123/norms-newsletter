"""The readability gate (SPEC 6.5, decision #14).

The syllable heuristic is the whole gate, so it is pinned by tests: if a
version bump shifted it, the publish/flag decision would shift with it. The
grade is asserted against a hand-computed value, and the grade-9 boundary,
the failing-sentence report, and the quote exclusion are each checked.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.editor import readability

FIXTURES = Path(__file__).resolve().parents[1] / "site" / "fixtures"


# --------------------------------------------------------------------------
# Syllable heuristic, pinned word by word
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "word,expected",
    [
        ("cat", 1),
        ("make", 1),      # silent trailing e
        ("table", 2),     # -le keeps its syllable
        ("agree", 2),     # -ee keeps both
        ("the", 1),       # count>1 guard keeps short words at 1
        ("be", 1),
        ("running", 2),
        ("regulation", 4),
        ("area", 2),      # vowel groups are "a" + "ea", the heuristic's known limit
        ("rhythm", 1),    # no vowel group, floored to 1
    ],
)
def test_count_syllables(word, expected):
    assert readability.count_syllables(word) == expected


def test_numerals_are_not_words():
    assert readability.words("We spent 52 billion dollars") == [
        "We", "spent", "billion", "dollars"
    ]


def test_grade_matches_hand_computation():
    # One sentence, seven words, each one syllable.
    text = "The cat sat on the big mat."
    words = ["The", "cat", "sat", "on", "the", "big", "mat"]
    assert readability.words(text) == words
    syllables = sum(readability.count_syllables(w) for w in words)
    expected = 0.39 * (7 / 1) + 11.8 * (syllables / 7) - 15.59
    assert readability.grade(text) == pytest.approx(expected)


def test_empty_text_grades_zero():
    assert readability.grade("") == 0.0
    assert readability.grade("   ") == 0.0


# --------------------------------------------------------------------------
# The boundary
# --------------------------------------------------------------------------
def test_plain_text_passes():
    text = "The dog ran. The cat sat. We had fun. It was a good day."
    assert readability.grade(text) <= readability.MAX_GRADE


def test_dense_text_fails():
    text = (
        "The unprecedented regulatory reconfiguration necessitated "
        "comprehensive institutional recalibration throughout numerous "
        "interdependent administrative subdivisions simultaneously."
    )
    assert readability.grade(text) > readability.MAX_GRADE


def test_report_reflects_pass_and_fail():
    hard = "word " * 3 + "".join(["institutionalization "] * 8) + "."
    edition = {
        "edition_type": "normal",
        "headline_of_the_day": "A calm day",
        "key_points": [],
        "sections": [
            {
                "name": "Technology",
                "stories": [
                    {
                        "slug": "easy",
                        "summary": "The dog ran. The cat sat. We had a good day.",
                        "article": None,
                    },
                    {
                        "slug": "hard",
                        "summary": hard,
                        "article": {
                            "background": hard,
                            "what_happened": hard,
                            "why_it_matters": hard,
                            "quote": None,
                        },
                    },
                ],
            }
        ],
    }
    report = readability.assess(edition)
    assert "hard" in report.failing_slugs
    assert "easy" not in report.failing_slugs


# --------------------------------------------------------------------------
# Quotes are measured but never revised (decision #15)
# --------------------------------------------------------------------------
def test_quote_counts_toward_story_text_but_not_revisable():
    story = {
        "summary": "A short summary.",
        "article": {
            "background": "Some background.",
            "what_happened": "It happened.",
            "why_it_matters": "It matters.",
            "quote": {"text": "An extraordinarily complicated verbatim utterance indeed."},
        },
    }
    assert "extraordinarily" in readability.story_text(story)
    assert "extraordinarily" not in readability.revisable_text(story)


# --------------------------------------------------------------------------
# Failing-sentence report
# --------------------------------------------------------------------------
def test_failing_sentences_returns_hardest_first():
    easy = "The cat sat."
    hard = (
        "Institutional recalibration necessitated comprehensive "
        "reconfiguration throughout numerous administrative subdivisions."
    )
    text = f"{easy} {hard}"
    flagged = readability.failing_sentences(text, threshold=9.0)
    assert flagged
    assert "Institutional" in flagged[0]
    assert easy not in flagged


# --------------------------------------------------------------------------
# The shipped fixtures read easily
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["normal", "quiet"])
def test_fixtures_pass_the_gate(name):
    edition = json.loads((FIXTURES / f"{name}.json").read_text())
    assert readability.assess(edition).passes
