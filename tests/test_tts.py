"""Text to speech (SPEC 6.7, decision #4).

The Gemini backend is exercised with a fake genai client, so no network and
no key. Duration is computed from PCM, so it is checked exactly. MP3
encoding runs for real (lameenc is a dependency), so the encoded bytes are
asserted non-empty.
"""

from __future__ import annotations

import json

import pytest

from src.config import AudioConfig
from src.audio import tts
from src.audio.schema import validate_script

from tests.test_audio_script import make_script_json


@pytest.fixture
def config() -> AudioConfig:
    return AudioConfig(
        script_model="claude-haiku-4-5-20251001",
        max_retries=1,
        tts_model="gemini-2.5-flash-preview-tts",
        speaker_a_voice="Kore",
        speaker_b_voice="Puck",
        min_words=10,
        max_words=20,
    )


def one_second_pcm() -> bytes:
    # 24 kHz, 16-bit, mono: one second is 24000 * 2 bytes.
    return b"\x00\x00" * tts.PCM_SAMPLE_RATE


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------
def test_transcript_labels_speakers() -> None:
    script = validate_script(
        {
            "turns": [
                {"speaker": "A", "text": "hello there"},
                {"speaker": "B", "text": "hi"},
                {"speaker": "A", "text": "ok"},
                {"speaker": "B", "text": "bye"},
            ]
        }
    )
    assert tts.transcript(script) == "A: hello there\nB: hi\nA: ok\nB: bye"


def test_pcm_duration_is_exact() -> None:
    assert tts.pcm_duration_seconds(one_second_pcm()) == 1
    assert tts.pcm_duration_seconds(one_second_pcm() * 3) == 3
    # Always at least one second, never zero.
    assert tts.pcm_duration_seconds(b"\x00\x00") == 1


def test_pcm_to_mp3_encodes() -> None:
    mp3 = tts.pcm_to_mp3(one_second_pcm())
    assert isinstance(mp3, bytes)
    assert len(mp3) > 0


def test_synthesized_size_is_byte_length() -> None:
    rendered = tts.Synthesized(audio_mpeg=b"abcde", duration_seconds=5)
    assert rendered.size_bytes == 5


# --------------------------------------------------------------------------
# GeminiSynthesizer with a fake client
# --------------------------------------------------------------------------
class _InlineData:
    def __init__(self, data):
        self.data = data


class _Part:
    def __init__(self, data):
        self.inline_data = _InlineData(data)


class _Content:
    def __init__(self, data):
        self.parts = [_Part(data)]


class _Candidate:
    def __init__(self, data):
        self.content = _Content(data)


class _GenResponse:
    def __init__(self, data):
        self.candidates = [_Candidate(data)]


class _FakeModels:
    def __init__(self, data):
        self._data = data
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        return _GenResponse(self._data)


class FakeGenaiClient:
    def __init__(self, data):
        self.models = _FakeModels(data)


def a_script():
    return validate_script(json.loads(make_script_json(15)))


def test_gemini_synthesizes_and_measures(config) -> None:
    client = FakeGenaiClient(one_second_pcm() * 2)
    synth = tts.GeminiSynthesizer(config, client=client)
    rendered = synth.synthesize(a_script())
    assert rendered.duration_seconds == 2
    assert rendered.size_bytes > 0
    assert client.models.calls == 1


def test_gemini_empty_audio_raises(config) -> None:
    synth = tts.GeminiSynthesizer(config, client=FakeGenaiClient(b""))
    with pytest.raises(tts.TTSError, match="no audio"):
        synth.synthesize(a_script())


def test_gemini_requires_a_key(config, monkeypatch) -> None:
    class _Settings:
        gemini_api_key = None

    monkeypatch.setattr(tts, "get_settings", lambda: _Settings())
    synth = tts.GeminiSynthesizer(config)  # no injected client
    with pytest.raises(tts.TTSError, match="GEMINI_API_KEY"):
        synth.synthesize(a_script())
