"""The headline repetition gate (SPEC 6.5, decision #24).

The fixtures here are the real 2026-07-22 and 2026-07-23 headlines, because
those are the ones that shipped the defect. The embedding is real too: this
gate's whole difficulty is what the model does or does not distinguish, so
faking it would test nothing.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from src.editor import headline_gate
from src.editor.headline_gate import PriorHeadline, check, recent_headlines

MODEL = "BAAI/bge-small-en-v1.5"
THRESHOLD = 0.80
TARGET = date(2026, 7, 23)

# What actually shipped.
PUBLISHED_0722 = "OpenAI models escaped test and broke into Hugging Face servers"
REPEAT_0723 = (
    "OpenAI's AI models broke out of testing and hacked Hugging Face to "
    "complete their task"
)
# What should have shipped: same story, but naming the new development.
GOOD_0723 = "Hugging Face says the OpenAI breach is a warning the industry ignored"

CONTINUES = [{"date": "2026-07-22", "summary": "OpenAI models hacked Hugging Face."}]
PRIOR = [PriorHeadline(date="2026-07-22", headline=PUBLISHED_0722, cluster_id="x" * 32)]


def _check(headline, prior=None, coverage=CONTINUES):
    return check(
        headline,
        PRIOR if prior is None else prior,
        threshold=THRESHOLD,
        model_name=MODEL,
        prior_coverage=coverage,
    )


# --------------------------------------------------------------------------
# The defect itself
# --------------------------------------------------------------------------
def test_the_real_duplicate_fires():
    result = _check(REPEAT_0723)
    assert result.repeated
    assert result.prior.date == "2026-07-22"
    assert result.similarity > THRESHOLD


def test_the_headline_that_should_have_shipped_passes():
    """Same story, same day, but it names what is new. Must not fire."""
    assert not _check(GOOD_0723).repeated


def test_feedback_names_the_offending_edition_and_invites_the_story():
    fb = _check(REPEAT_0723).feedback()
    assert "2026-07-22" in fb
    assert PUBLISHED_0722 in fb
    # It must not read as "do not lead with this story again".
    assert "may still lead" in fb


# --------------------------------------------------------------------------
# The conjunction. Text alone is not sufficient evidence; these are the
# cases that made the gate require story identity as well.
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "prior_headline,todays_headline",
    [
        # Measured 0.836: the embedding cannot tell "blocks" from "approves".
        (
            "Federal judge blocks Paramount-Warner Bros merger on antitrust grounds",
            "Federal judge approves Paramount-Warner Bros merger after appeal",
        ),
        # Measured 0.844: same template, different country.
        (
            "Trump imposes 50% tariffs on Canadian goods in trade retaliation",
            "Trump imposes 25% tariffs on Mexican goods in trade retaliation",
        ),
        # Measured 0.838: same template, different companies.
        (
            "Federal judge blocks Paramount-Warner Bros merger on antitrust grounds",
            "Federal judge blocks Kroger-Albertsons merger on antitrust grounds",
        ),
    ],
)
def test_structurally_similar_but_unrelated_headlines_do_not_fire(
    prior_headline, todays_headline
):
    """These score above threshold on text, and are different stories.

    Without the story-identity half of the conjunction the gate would block
    a legitimate headline, which is worse than the defect it fixes.
    """
    prior = [PriorHeadline(date="2026-07-22", headline=prior_headline, cluster_id=None)]
    assert not _check(todays_headline, prior=prior, coverage=[]).repeated


def test_no_prior_coverage_means_no_fire_however_similar():
    assert not _check(REPEAT_0723, coverage=[]).repeated
    assert not _check(REPEAT_0723, coverage=None).repeated


def test_coverage_of_a_different_day_does_not_fire():
    """The story continues something, but not the edition being compared."""
    other = [{"date": "2026-07-18", "summary": "Something else entirely."}]
    assert not _check(REPEAT_0723, coverage=other).repeated


# --------------------------------------------------------------------------
# Reading the publication record
# --------------------------------------------------------------------------
def _write(dirpath, day, headline, *, edition_type="normal"):
    payload = {"date": day, "edition_number": 1, "edition_type": edition_type}
    if headline is not None:
        payload["headline_of_the_day"] = headline
    (dirpath / f"{day}.json").write_text(json.dumps(payload))


def test_reads_headlines_inside_the_window(tmp_path):
    _write(tmp_path, "2026-07-22", PUBLISHED_0722)
    got = recent_headlines(TARGET, 7, tmp_path)
    assert [p.date for p in got] == ["2026-07-22"]


def test_excludes_the_target_date_itself(tmp_path):
    """Re-running a published date must not flag it against its own headline.

    run_edition can re-run a date, and by then that edition is on disk.
    """
    _write(tmp_path, "2026-07-23", REPEAT_0723)
    assert recent_headlines(TARGET, 7, tmp_path) == []


def test_excludes_editions_outside_the_window(tmp_path):
    _write(tmp_path, "2026-07-10", PUBLISHED_0722)
    assert recent_headlines(TARGET, 7, tmp_path) == []


def test_skips_fallback_editions(tmp_path):
    """A fallback carries no headline_of_the_day at all (SPEC 6.5)."""
    _write(tmp_path, "2026-07-22", None, edition_type="fallback")
    assert recent_headlines(TARGET, 7, tmp_path) == []


def test_missing_directory_is_not_an_error(tmp_path):
    assert recent_headlines(TARGET, 7, tmp_path / "nope") == []


def test_unreadable_edition_is_skipped_not_fatal(tmp_path):
    (tmp_path / "2026-07-22.json").write_text("{not json")
    _write(tmp_path, "2026-07-21", PUBLISHED_0722)
    assert [p.date for p in recent_headlines(TARGET, 7, tmp_path)] == ["2026-07-21"]


def test_no_prior_editions_means_no_gate(tmp_path):
    assert not check(
        REPEAT_0723, [], threshold=THRESHOLD, model_name=MODEL, prior_coverage=CONTINUES
    ).repeated
