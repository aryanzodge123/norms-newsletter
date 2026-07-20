"""The dialogue-script schema and the one AI call (SPEC 6.7).

Anthropic is stubbed at the client boundary, the same seam
tests/test_writer_stage.py uses. No network, no key.
"""

from __future__ import annotations

import json

import pytest

from src.config import AudioConfig
from src.audio import script as script_stage
from src.audio.schema import ScriptInvalid, validate_script
from src.editor.llm import AIFailure

from tests.test_writer_stage import FakeClient


def make_script_json(total_words: int) -> str:
    """A structurally valid two-host script with a known word count.

    Three fixed short turns carry 4 words; the lead turn carries the rest,
    so word_count is exactly total_words (total_words >= 5).
    """
    lead = " ".join(["word"] * (total_words - 4))
    turns = [
        {"speaker": "A", "text": lead},
        {"speaker": "B", "text": "yes ok"},
        {"speaker": "A", "text": "sure"},
        {"speaker": "B", "text": "right"},
    ]
    return json.dumps({"turns": turns})


@pytest.fixture
def config() -> AudioConfig:
    # A narrow band so tests can straddle it with small scripts.
    return AudioConfig(
        script_model="claude-haiku-4-5-20251001",
        max_retries=1,
        tts_model="gemini-2.5-flash-preview-tts",
        speaker_a_voice="Kore",
        speaker_b_voice="Puck",
        min_words=10,
        max_words=20,
    )


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------
def test_valid_script_parses() -> None:
    script = validate_script(json.loads(make_script_json(15)))
    assert script.word_count == 15
    assert len(script.turns) == 4


def test_rejects_a_single_host() -> None:
    obj = {"turns": [{"speaker": "A", "text": f"line {i}"} for i in range(4)]}
    with pytest.raises(ScriptInvalid, match="both speakers"):
        validate_script(obj)


def test_rejects_too_few_turns() -> None:
    obj = {"turns": [{"speaker": "A", "text": "hi"}, {"speaker": "B", "text": "yo"}]}
    with pytest.raises(ScriptInvalid):
        validate_script(obj)


def test_rejects_an_em_dash() -> None:
    obj = json.loads(make_script_json(15))
    obj["turns"][0]["text"] = "this line has an em dash — right here now"
    with pytest.raises(ScriptInvalid, match="em dash"):
        validate_script(obj)


def test_rejects_unknown_speaker() -> None:
    obj = {"turns": [{"speaker": "C", "text": "x"}] * 4}
    with pytest.raises(ScriptInvalid):
        validate_script(obj)


# --------------------------------------------------------------------------
# generate_script
# --------------------------------------------------------------------------
def test_first_reply_in_band(config) -> None:
    client = FakeClient([make_script_json(15)])
    result = script_stage.generate_script(client, {"date": "2026-07-19"}, config, "sys")
    assert result.within_band is True
    assert result.script.word_count == 15
    assert client.messages.calls == 1


def test_retries_when_off_band_then_succeeds(config) -> None:
    client = FakeClient([make_script_json(40), make_script_json(15)])
    result = script_stage.generate_script(client, {"date": "2026-07-19"}, config, "sys")
    assert result.within_band is True
    assert client.messages.calls == 2


def test_accepts_off_band_after_retries(config) -> None:
    client = FakeClient([make_script_json(40), make_script_json(40)])
    result = script_stage.generate_script(client, {"date": "2026-07-19"}, config, "sys")
    assert result.within_band is False
    assert result.script.word_count == 40
    assert client.messages.calls == 2


def test_invalid_twice_raises(config) -> None:
    client = FakeClient(["not json at all", json.dumps({"turns": []})])
    with pytest.raises(AIFailure):
        script_stage.generate_script(client, {"date": "2026-07-19"}, config, "sys")
    assert client.messages.calls == 2
