"""Text to speech (SPEC 6.7, decision #4).

The Gemini backend is exercised with a fake genai client, so no network and
no key. Duration is computed from PCM, so it is checked exactly. MP3
encoding runs for real (lameenc is a dependency), so the encoded bytes are
asserted non-empty.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

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
    def __init__(self, data, usage=None):
        self.candidates = [_Candidate(data)]
        if usage is not None:
            self.usage_metadata = usage


class _FakeModels:
    def __init__(self, data, usage=None):
        self._data = data
        self._usage = usage
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        return _GenResponse(self._data, self._usage)


class FakeGenaiClient:
    def __init__(self, data, usage=None):
        self.models = _FakeModels(data, usage)


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


# --------------------------------------------------------------------------
# TTS cost estimate (SPEC 6.7)
# --------------------------------------------------------------------------
def _priced(config) -> AudioConfig:
    return config.model_copy(
        update={"tts_price_input_per_mtok": 0.50, "tts_price_output_per_mtok": 10.00}
    )


def test_estimate_tts_cost_is_priced_per_token(config) -> None:
    usage = SimpleNamespace(prompt_token_count=2_000, candidates_token_count=5_000)
    # (2000 * 0.50 + 5000 * 10.00) / 1e6 = 0.051
    assert tts.estimate_tts_cost_usd(usage, _priced(config)) == pytest.approx(0.051)


def test_estimate_tts_cost_handles_missing_usage(config) -> None:
    priced = _priced(config)
    assert tts.estimate_tts_cost_usd(None, priced) == 0.0
    # A usage object missing the token fields prices at 0.0, not a crash.
    assert tts.estimate_tts_cost_usd(SimpleNamespace(), priced) == 0.0


def test_synthesize_prices_the_render(config) -> None:
    usage = SimpleNamespace(prompt_token_count=1_000, candidates_token_count=1_000)
    client = FakeGenaiClient(one_second_pcm(), usage=usage)
    rendered = tts.GeminiSynthesizer(_priced(config), client=client).synthesize(a_script())
    # (1000 * 0.50 + 1000 * 10.00) / 1e6 = 0.0105
    assert rendered.cost_usd == pytest.approx(0.0105)


def test_synthesize_without_usage_costs_zero(config) -> None:
    client = FakeGenaiClient(one_second_pcm())  # response carries no usage_metadata
    rendered = tts.GeminiSynthesizer(_priced(config), client=client).synthesize(a_script())
    assert rendered.cost_usd == 0.0


# --------------------------------------------------------------------------
# Client construction: the render call must be bounded
# --------------------------------------------------------------------------
def test_client_is_built_with_the_configured_timeout(monkeypatch, config) -> None:
    """An un-timed TTS call hung the 2026-08-26 publish for six hours with the
    day's edition built and uncommitted. synthesize() turns a raise into
    "publish without audio", but it can contain nothing that never returns, so
    the ceiling has to be on the client itself. HttpOptions.timeout is
    milliseconds, which is the part that is easy to get wrong."""
    import google.genai as genai

    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(models=SimpleNamespace())

    monkeypatch.setattr(genai, "Client", fake_client)
    monkeypatch.setattr(tts, "get_settings", lambda: SimpleNamespace(gemini_api_key="k"))

    tts.GeminiSynthesizer(config)._get_client()

    assert captured["api_key"] == "k"
    assert captured["http_options"].timeout == int(config.tts_timeout_seconds * 1000)
    # The shipped default, raised from 300.0 after the 2026-09-14 measurement:
    # a typical render is about 160 s, so 300 s was 1.9x a normal render rather
    # than the headroom its comment claimed. 360 s keeps one retry inside the
    # audio step's 900 s ceiling (60 + 360 + 30 + 360 = 810).
    assert config.tts_timeout_seconds == 360.0


def test_missing_key_raises_rather_than_building_an_untimed_client(monkeypatch, config) -> None:
    monkeypatch.setattr(tts, "get_settings", lambda: SimpleNamespace(gemini_api_key=None))
    with pytest.raises(tts.TTSError, match="GEMINI_API_KEY"):
        tts.GeminiSynthesizer(config)._get_client()


# --------------------------------------------------------------------------
# Transient vs permanent, and the bounded retry (SPEC 6.7, decision #66)
#
# The classification is the load-bearing half. Before it, a bare
# `except Exception` made a missing API key and a 503 indistinguishable, so a
# retry loop would have spent the audio step's whole budget re-attempting
# failures that could not succeed.
# --------------------------------------------------------------------------
class _StatusError(Exception):
    """Stands in for google.genai.errors.APIError, which carries `code`."""

    def __init__(self, code, message=""):
        super().__init__(message or f"{code} something")
        self.code = code


class ReadTimeout(Exception):
    """Stands in for httpx.ReadTimeout: a name, not a status or a phrase.

    Deliberately named exactly as httpx names it, because the classifier
    matches on the class names in the MRO rather than on imported types, so
    the name is the contract being tested.
    """


class _RetryingModels:
    """Raises the queued errors in order, then returns audio."""

    def __init__(self, errors, data):
        self._errors = list(errors)
        self._data = data
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        if self._errors:
            raise self._errors.pop(0)
        return _GenResponse(self._data)


class RetryingClient:
    def __init__(self, errors, data):
        self.models = _RetryingModels(errors, data)


class Clock:
    """A fake sleep. The suite must never actually wait out a 30s backoff."""

    def __init__(self):
        self.slept = []

    def __call__(self, seconds):
        self.slept.append(seconds)


@pytest.mark.parametrize(
    "exc",
    [
        _StatusError(429),
        _StatusError(500),
        _StatusError(502),
        _StatusError(503, "503 UNAVAILABLE. The model is overloaded."),
        _StatusError(504),
        # The three failures actually observed 2026-09-09 to 2026-09-14.
        RuntimeError("Server disconnected without sending a response."),
        RuntimeError("The read operation timed out"),
        RuntimeError(
            "503 UNAVAILABLE. The service is currently unavailable due to high "
            "demand. Please try again later."
        ),
        # Typed transport failures that carry neither a status nor a phrase.
        ReadTimeout(),
        TimeoutError(),
        ConnectionResetError(),
    ],
)
def test_transient_failures_are_classified_transient(exc) -> None:
    assert tts.is_transient(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        _StatusError(400, "invalid argument"),
        _StatusError(401, "unauthenticated"),
        _StatusError(403, "permission denied"),
        _StatusError(404, "model not found"),
        tts.TTSError("GEMINI_API_KEY is required for audio synthesis."),
        ValueError("something the SDK did not document"),
        AttributeError("'NoneType' object has no attribute 'parts'"),
        IndexError("list index out of range"),
    ],
)
def test_permanent_failures_are_classified_permanent(exc) -> None:
    assert tts.is_transient(exc) is False


# Every TTS failure actually observed in a publish run between 2026-08-07 and
# 2026-09-14, taken from the Actions logs. These are the messages the retry
# exists for, so the classifier is pinned against them rather than against
# invented examples. The 500 INTERNAL row is why LEADING_STATUS exists: it is
# the one failure the message fragments alone did not catch.
OBSERVED_PRODUCTION_FAILURES = [
    "500 INTERNAL. {'error': {'code': 500, 'message': 'Internal error'}}",
    "Server disconnected without sending a response.",
    "The read operation timed out",
    (
        "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is "
        "currently experiencing high demand. Spikes in demand are usually "
        "temporary. Please try again later.', 'status': 'UNAVAILABLE'}}"
    ),
]


@pytest.mark.parametrize("message", OBSERVED_PRODUCTION_FAILURES)
def test_every_observed_production_failure_is_transient(message: str) -> None:
    """Each of these cost a real edition its audio and none was retried."""
    assert tts.is_transient(Exception(message)) is True


@pytest.mark.parametrize(
    "message",
    [
        "400 INVALID_ARGUMENT. {'error': {'code': 400}}",
        "401 UNAUTHENTICATED",
        "403 PERMISSION_DENIED",
        "404 NOT_FOUND",
        # Starts with three digits that are not a status. The pattern must not
        # read a count, an id or a byte size as an HTTP code.
        "200 items failed to parse",
        "128 bytes of audio returned",
    ],
)
def test_a_leading_number_that_is_not_a_transient_status_is_permanent(
    message: str,
) -> None:
    assert tts.is_transient(Exception(message)) is False


def test_an_unrecognized_error_is_permanent_on_purpose() -> None:
    """The deliberate direction to be wrong in (decision #66).

    A new transient class costs one day's audio and leaves a log line to
    classify. Defaulting the other way costs the render budget every morning,
    retrying failures that cannot succeed.
    """

    class SomethingNobodyHasSeen(Exception):
        pass

    assert tts.is_transient(SomethingNobodyHasSeen("brand new failure mode")) is False


def test_a_wrapped_transient_cause_is_still_transient() -> None:
    """The genai SDK wraps the transport error, so the timeout that actually
    happened is often two __cause__ links below what reaches the caller."""
    inner = ReadTimeout()
    outer = RuntimeError("the call failed")
    outer.__cause__ = inner
    assert tts.is_transient(outer) is True


def test_a_boolean_code_is_not_read_as_a_status() -> None:
    """bools are ints in Python, so `code=True` would otherwise read as 1."""

    class _Odd(Exception):
        code = True

    assert tts.is_transient(_Odd("no")) is False


def test_transient_failure_then_success_returns_audio(config) -> None:
    clock = Clock()
    client = RetryingClient([_StatusError(503)], one_second_pcm())
    synth = tts.GeminiSynthesizer(config, client=client, sleep=clock)

    rendered = synth.synthesize(a_script())

    assert rendered.duration_seconds == 1
    assert rendered.attempts == 2
    assert client.models.calls == 2
    assert clock.slept == [config.tts_retry_backoff_seconds]


def test_two_transient_failures_raise_so_the_caller_ships_without_audio(config) -> None:
    clock = Clock()
    client = RetryingClient(
        [_StatusError(503), RuntimeError("Server disconnected without sending a response.")],
        one_second_pcm(),
    )
    synth = tts.GeminiSynthesizer(config, client=client, sleep=clock)

    with pytest.raises(tts.TTSError, match="Gemini TTS call failed"):
        synth.synthesize(a_script())

    # One retry and not two: the step budget affords a second attempt, not a
    # third (decision #66).
    assert client.models.calls == 2
    assert len(clock.slept) == 1


def test_a_permanent_failure_is_not_retried(config) -> None:
    clock = Clock()
    client = RetryingClient([_StatusError(401, "unauthenticated")], one_second_pcm())
    synth = tts.GeminiSynthesizer(config, client=client, sleep=clock)

    with pytest.raises(tts.TTSError, match="Gemini TTS call failed"):
        synth.synthesize(a_script())

    assert client.models.calls == 1
    assert clock.slept == []


def test_retries_can_be_configured_off(config) -> None:
    """tts_max_retries: 0 restores the pre-#66 single attempt exactly."""
    clock = Clock()
    client = RetryingClient([_StatusError(503)], one_second_pcm())
    synth = tts.GeminiSynthesizer(
        config.model_copy(update={"tts_max_retries": 0}), client=client, sleep=clock
    )

    with pytest.raises(tts.TTSError):
        synth.synthesize(a_script())

    assert client.models.calls == 1
    assert clock.slept == []


def test_an_empty_payload_is_permanent_and_not_retried(config) -> None:
    """Empty PCM is a successful call that returned nothing. A second identical
    call cannot change that, so it must not consume the retry."""
    clock = Clock()
    client = RetryingClient([], b"")
    synth = tts.GeminiSynthesizer(config, client=client, sleep=clock)

    with pytest.raises(tts.TTSError, match="no audio"):
        synth.synthesize(a_script())

    assert client.models.calls == 1
    assert clock.slept == []


def test_a_clean_render_reports_one_attempt(config) -> None:
    """`attempts` is what makes tts_wall_seconds interpretable: only a row with
    one attempt is a render measurement rather than a render plus a backoff."""
    synth = tts.GeminiSynthesizer(config, client=FakeGenaiClient(one_second_pcm()))
    assert synth.synthesize(a_script()).attempts == 1
