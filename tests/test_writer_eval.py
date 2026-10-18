"""The writer eval's grounding check and arm parsing (scripts/writer_eval.py).

The eval itself calls the API and is run by hand. What it reports is only as
good as the grounding check, which is deterministic, so that is what is
tested: it must list a fact the source never gave, and it must not list the
ordinary rewordings a faithful article makes.
"""

from __future__ import annotations

import argparse

import pytest

from scripts.writer_eval import Arm, RecordingClient, parse_arm, ungrounded_candidates

SOURCE = (
    "Title: Masked settlers attack European diplomats in the occupied West Bank\n"
    "excerpt: Diplomats from France and Germany were attacked on October 19 near "
    "Ramallah, the U.S. State Department said. About 1,200 settlers live nearby, "
    "and three vehicles were damaged. Prices rose 4.5% this year."
)


def tokens(article: str) -> set[str]:
    return {c.token for c in ungrounded_candidates(article, SOURCE)}


class TestFlagsWhatTheSourceNeverSaid:
    def test_a_year_from_the_models_own_knowledge(self) -> None:
        """The case that started this: true, but not in the sources."""
        article = "Settlers live on land Israel captured in 1967, near Ramallah."
        assert {"1967", "Israel"} <= tokens(article)

    def test_an_invented_number(self) -> None:
        assert tokens("About 5,000 settlers live nearby.") == {"5,000"}

    def test_an_invented_name(self) -> None:
        assert "Spain" in tokens("Diplomats from France and Spain were attacked.")

    def test_each_candidate_carries_its_sentence(self) -> None:
        [candidate] = ungrounded_candidates("Officials said 7 people were hurt.", SOURCE)
        assert candidate.kind == "number"
        assert candidate.sentence == "Officials said 7 people were hurt."


class TestDoesNotFlagFaithfulRewording:
    def test_numbers_formatted_differently(self) -> None:
        assert tokens("About 1200 settlers live there, and prices rose 4.5%.") == set()

    def test_a_number_the_source_spelled_out(self) -> None:
        assert tokens("Officials said 3 vehicles were damaged.") == set()

    def test_a_day_from_an_iso_date_in_prior_mentions(self) -> None:
        """Prior mentions carry ISO dates; "2026-10-02" grounds "October 2"."""
        source = SOURCE + "\nPrior mentions:\n- 2026-10-02: Earlier coverage."
        assert {c.token for c in ungrounded_candidates("Norm covered it on October 2.", source)} == set()

    def test_an_abbreviated_month(self) -> None:
        assert tokens("The attack happened on Oct. 19 near Ramallah.") == set()

    def test_possessives_and_acronyms(self) -> None:
        assert tokens("It was the U.S. State Department's statement on Germany's diplomats.") == set()

    def test_the_first_word_of_a_sentence(self) -> None:
        """Capitalised because it starts the sentence, not because it is a name."""
        assert tokens("Officials described the attack near Ramallah.") == set()

    def test_the_pronoun_i(self) -> None:
        assert tokens("Here I note that France was involved.") == set()


class TestArmParsing:
    def test_model_only(self) -> None:
        assert parse_arm("old=claude-haiku-4-5-20251001") == Arm("old", "claude-haiku-4-5-20251001")

    def test_model_effort_and_cap(self) -> None:
        assert parse_arm("new=claude-haiku-5-5:medium:8192") == Arm("new", "claude-haiku-5-5", "medium", 8192)

    def test_cap_without_effort(self) -> None:
        assert parse_arm("new=claude-haiku-5-5::4096") == Arm("new", "claude-haiku-5-5", None, 4096)

    @pytest.mark.parametrize("spec", ["claude-haiku-5-5", "=claude-haiku-5-5", "x=a:b:1:2"])
    def test_rejects_malformed(self, spec: str) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            parse_arm(spec)


class TestRecordingClient:
    """The arm's effort wins over whatever the writer stage sent."""

    class _Inner:
        def __init__(self) -> None:
            self.sent: dict = {}
            self.messages = self

        def create(self, **kwargs):
            self.sent = kwargs

            class _Usage:
                output_tokens = 1

            class _Response:
                stop_reason = "end_turn"
                usage = _Usage()

            return _Response()

    def send(self, arm: Arm, output_config: dict) -> dict:
        inner = self._Inner()
        RecordingClient(inner, arm, []).create(max_tokens=2048, output_config=output_config)
        return inner.sent

    def test_an_arm_without_effort_strips_the_configs_effort(self) -> None:
        sent = self.send(Arm("old", "claude-haiku-4-5-20251001"), {"format": "f", "effort": "medium"})
        assert sent["output_config"] == {"format": "f"}

    def test_an_arm_with_effort_overrides_it(self) -> None:
        sent = self.send(Arm("new", "claude-haiku-5-5", "low", 8192), {"format": "f", "effort": "medium"})
        assert sent["output_config"] == {"format": "f", "effort": "low"}
        assert sent["max_tokens"] == 8192
