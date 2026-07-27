"""The editor prompt builder (SPEC 6.5, Finding 5).

`build_user_message` and `_mode_line` render the candidate list and the
constraints the editor sees, including the `prior_coverage` block that makes
continuing coverage work. It was previously untested: the gate on the
editor's output has coverage, but the input that feeds it did not, so a silent
break in rendering would pass every test while the editor stopped being told
about yesterday. Pure string building, no AI, fully offline.
"""
from __future__ import annotations

from src.editor import run_editor
from src.editor.plan import plan_sections
from src.editor.schema import TOPICS

from tests.test_run_edition import ctx


def _contexts():
    # Two Tech (an available section), one Science (held: only one story).
    return [
        ctx("a" * 32, topic="Tech", headline="Chips get faster"),
        ctx("b" * 32, topic="Tech", headline="A new framework ships"),
        ctx("c" * 32, topic="Science", headline="A quiet proof lands"),
    ]


def test_candidate_block_carries_the_pipeline_facts():
    contexts = _contexts()
    msg = run_editor.build_user_message(contexts, "normal", plan_sections(contexts))
    assert "cluster_id: " + "a" * 32 in msg
    assert "topic: Tech" in msg
    assert "score: 7" in msg
    assert "headline: Chips get faster" in msg


def test_prior_coverage_block_appears_only_for_covered_candidates():
    contexts = _contexts()
    prior_coverage = {
        "a" * 32: [{"date": "2026-07-24", "summary": "We covered the chip roadmap yesterday."}],
    }
    msg = run_editor.build_user_message(
        contexts, "normal", plan_sections(contexts), prior_coverage=prior_coverage
    )
    # The covered candidate gets the block; the exact mechanism Finding 5 flags.
    assert "prior_coverage: 2026-07-24: We covered the chip roadmap yesterday." in msg
    # Exactly one prior_coverage line: the other two candidates have none.
    assert msg.count("prior_coverage:") == 1


def test_no_prior_coverage_means_no_block():
    contexts = _contexts()
    msg = run_editor.build_user_message(contexts, "normal", plan_sections(contexts))
    assert "prior_coverage:" not in msg


def test_mode_line_normal_vs_quiet_point_counts():
    contexts = _contexts()
    plan = plan_sections(contexts)
    normal = run_editor.build_user_message(contexts, "normal", plan)
    quiet = run_editor.build_user_message(contexts, "quiet", plan)
    assert "Write 4 to 6 glance points" in normal
    assert "Write 3 to 3 glance points" in quiet
    # The 15-to-20 total instruction is a normal-only guard (decision #29).
    assert "15 to 20 stories" in normal
    assert "15 to 20 stories" not in quiet


def test_mode_line_lists_available_and_held_sections():
    contexts = _contexts()
    msg = run_editor.build_user_message(contexts, "normal", plan_sections(contexts))
    assert "Technology" in msg  # available (two Tech stories)
    # The lone Science story is held to briefly.
    assert "put their stories in" in msg and "Science" in msg


def test_glance_topics_are_the_codes_not_section_names():
    contexts = _contexts()
    msg = run_editor.build_user_message(contexts, "normal", plan_sections(contexts))
    # Guards the 2026-07-24 retry: point topics must be the short codes.
    assert "Tag each glance point with a topic code" in msg
    for code in TOPICS:
        assert code in msg


def test_repeat_feedback_is_appended_when_set():
    contexts = _contexts()
    plan = plan_sections(contexts)
    feedback = "The headline restates 2026-07-24: name the new development."
    with_fb = run_editor.build_user_message(
        contexts, "normal", plan, repeat_feedback=feedback
    )
    without_fb = run_editor.build_user_message(contexts, "normal", plan)
    assert feedback in with_fb
    assert feedback not in without_fb
