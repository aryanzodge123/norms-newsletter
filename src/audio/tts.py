"""Text to speech (SPEC 6.7, decision #4).

Multi-speaker TTS behind a swappable interface. The default backend is
Gemini multi-speaker TTS; swapping it is a config change (audio.tts_model,
the two voice names) plus a new Synthesizer, not a change to the caller.

The interface returns the encoded MP3 together with its exact duration.
Duration is computed from the raw PCM sample count before encoding, so it is
exact and needs no MP3 parsing; size is just the length of the encoded
bytes. A backend that cannot produce audio raises TTSError, which the caller
turns into "publish without an audio row" (SPEC 7).

A transient failure of the render is retried once before that happens
(decision #66), inside the Synthesizer rather than in the caller, so the
retry survives decision #44's rework of the per-edition orchestration.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Protocol

from ..config import AudioConfig, get_settings
from .schema import DialogueScript

log = logging.getLogger(__name__)

# Gemini TTS returns signed 16-bit little-endian mono PCM at 24 kHz.
PCM_SAMPLE_RATE = 24_000
PCM_BYTES_PER_SAMPLE = 2
PCM_CHANNELS = 1
MP3_BITRATE_KBPS = 96

# --------------------------------------------------------------------------
# Transient vs permanent (SPEC 6.7, decision #66)
#
# The retry is the easy half. The classification is the half that has to be
# right, because the old bare `except Exception` made a missing API key and a
# 503 indistinguishable, and a retry loop over that spends the audio step's
# whole budget re-attempting a failure that cannot succeed.
#
# The rule everywhere below: recognized transport and availability failures
# are transient, and **everything else is permanent**, including an error this
# module has never seen. That direction is deliberate. Being wrong about a new
# transient class costs one day's audio and leaves a log line to classify;
# being wrong about a permanent one costs the render budget every morning.
# --------------------------------------------------------------------------

# HTTP statuses worth a second attempt: rate limiting and the 5xx family the
# provider itself describes as temporary. 400, 401, 403 and 404 are absent on
# purpose, since re-sending the same request cannot change any of them.
TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# Exception class names, matched anywhere in the raised type's MRO, so a
# subclass of a known transient error is still transient. Names rather than
# imported types because these come from httpx and google.genai, neither of
# which this module should have to import just to classify a failure, and a
# backend swap (the whole point of the Synthesizer interface) brings its own
# exception hierarchy with it.
TRANSIENT_EXCEPTION_NAMES = frozenset(
    {
        # builtins: socket.timeout is TimeoutError, and a dropped socket is a
        # ConnectionError subclass.
        "TimeoutError",
        "ConnectionError",
        # httpx, which is what the google.genai client uses underneath.
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "TimeoutException",
        "ConnectError",
        "ReadError",
        "WriteError",
        "RemoteProtocolError",
        # google.genai.errors: ServerError covers the whole 5xx family.
        "ServerError",
    }
)

# Message fragments, lowercased, for the failures that arrive as a plain
# message rather than as a typed exception or a status code. Every one of
# these is taken from a failure actually observed between 2026-09-09 and
# 2026-09-14, not invented: "Server disconnected without sending a response.",
# "503 UNAVAILABLE ... high demand ... Please try again later.", and "The read
# operation timed out". They are phrases rather than single words so that an
# unrelated message cannot match one by accident.
# The genai SDK formats an API error's str() as "503 UNAVAILABLE. {...}", so
# when the failure arrives as a plain message rather than a typed exception the
# status is still there, just at the front of the string. Anchored to the start
# and bounded by a space so it reads a status and not the first three digits of
# some number inside the message.
LEADING_STATUS = re.compile(r"^\s*(\d{3})\b")


TRANSIENT_MESSAGE_FRAGMENTS = (
    "server disconnected",
    "connection reset",
    "connection aborted",
    "timed out",
    "deadline exceeded",
    "unavailable",
    "try again later",
    "overloaded",
)


def _status_code(exc: BaseException) -> int | None:
    """The HTTP status an exception carries, if it carries one as an int.

    google.genai.errors.APIError exposes it as `code`; httpx responses and
    several other clients call it `status_code`. Anything non-integer (a
    string error code, an enum) is ignored rather than coerced, because a
    guess here decides whether the render is attempted again.
    """
    for attribute in ("code", "status_code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, bool):  # bools are ints; never a status
            continue
        if isinstance(value, int):
            return value
    return None


def is_transient(exc: BaseException) -> bool:
    """True if this failure is worth exactly one more attempt (decision #66).

    Checks three signals in turn, because the same upstream problem reaches us
    in three shapes depending on where it was raised: a status code, a typed
    transport exception, or a bare message. A failure matching none of them is
    permanent, which is the deliberate default described above.

    The chained causes are inspected too. The genai SDK wraps a transport
    error in its own exception type, so the httpx timeout that actually
    happened is often two `__cause__` links down from what reaches the caller.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))

        status = _status_code(current)
        if status is not None and status in TRANSIENT_STATUS_CODES:
            return True

        names = {klass.__name__ for klass in type(current).__mro__}
        if names & TRANSIENT_EXCEPTION_NAMES:
            return True

        message = str(current)
        leading = LEADING_STATUS.match(message)
        if leading and int(leading.group(1)) in TRANSIENT_STATUS_CODES:
            return True

        lowered = message.lower()
        if any(fragment in lowered for fragment in TRANSIENT_MESSAGE_FRAGMENTS):
            return True

        current = current.__cause__ or current.__context__
    return False


class TTSError(RuntimeError):
    """The audio could not be synthesized. The caller ships without audio."""


@dataclass(frozen=True)
class Synthesized:
    """One rendered dialogue: the MP3 bytes, its exact duration, and the
    estimated USD cost of the TTS render (0.0 for a backend that reports no
    token usage)."""

    audio_mpeg: bytes
    duration_seconds: int
    cost_usd: float = 0.0
    # How many attempts the render took (decision #66). 1 is a clean render,
    # and anything higher means `tts_wall_seconds` on the run_log row includes
    # a failed attempt plus a backoff, so it is not a render measurement. The
    # latency series proposal C asks for is the subset where this is 1.
    attempts: int = 1

    @property
    def size_bytes(self) -> int:
        return len(self.audio_mpeg)


def estimate_tts_cost_usd(usage, config: AudioConfig) -> float:
    """Estimate the render cost from a Gemini usage_metadata object and the
    per-token prices in config (SPEC 6.7). Mirrors score.estimate_cost_usd:
    token fields are read defensively, so a missing field or a None usage
    (a fake client, or a response without metadata) prices at 0.0 rather
    than crashing the publish."""
    if usage is None:
        return 0.0
    prompt = getattr(usage, "prompt_token_count", 0) or 0
    output = getattr(usage, "candidates_token_count", 0) or 0
    return (
        prompt * config.tts_price_input_per_mtok
        + output * config.tts_price_output_per_mtok
    ) / 1_000_000


class Synthesizer(Protocol):
    """Turns a validated dialogue into MP3 audio."""

    def synthesize(self, script: DialogueScript) -> Synthesized: ...


def transcript(script: DialogueScript) -> str:
    """The dialogue as speaker-labelled lines the TTS backend narrates."""
    return "\n".join(f"{turn.speaker}: {turn.text}" for turn in script.turns)


def pcm_duration_seconds(pcm: bytes) -> int:
    """Exact duration of raw PCM, rounded to whole seconds (min 1)."""
    frames = len(pcm) / (PCM_SAMPLE_RATE * PCM_BYTES_PER_SAMPLE * PCM_CHANNELS)
    return max(1, round(frames))


def pcm_to_mp3(pcm: bytes) -> bytes:
    """Encode 24 kHz mono 16-bit PCM to MP3.

    Uses lameenc, a pip-installable encoder that needs no system ffmpeg, so
    the mini PC and CI both encode the same way. Imported lazily and raised
    as TTSError if unavailable, so a box without the encoder ships the
    edition without audio rather than crashing the publish (SPEC 7).
    """
    try:
        import lameenc
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise TTSError(
            "lameenc is required to encode MP3 audio; install it or the "
            "edition ships without an audio row (SPEC 7)"
        ) from exc

    encoder = lameenc.Encoder()
    encoder.set_bit_rate(MP3_BITRATE_KBPS)
    encoder.set_in_sample_rate(PCM_SAMPLE_RATE)
    encoder.set_channels(PCM_CHANNELS)
    encoder.set_quality(2)
    return bytes(encoder.encode(pcm)) + bytes(encoder.flush())


class GeminiSynthesizer:
    """Gemini multi-speaker TTS (decision #4).

    Maps the two dialogue speakers A and B onto the two configured prebuilt
    voices, sends the labelled transcript, and encodes the returned PCM to
    MP3. The Gemini key comes from config.get_settings(); this class never
    reads the environment itself.
    """

    def __init__(self, config: AudioConfig, *, client=None, sleep=time.sleep) -> None:
        self.config = config
        self._client = client
        # Injected so a test can assert the backoff without waiting it out.
        # The retry is bounded and short in production, but a suite that
        # actually slept 30 seconds to prove it would stop being run.
        self._sleep = sleep

    def _get_client(self):
        if self._client is not None:
            return self._client
        from google import genai
        from google.genai import types

        settings = get_settings()
        if not settings.gemini_api_key:
            raise TTSError(
                "GEMINI_API_KEY is required for audio synthesis. Set it in .env "
                "locally or as an Actions secret in CI (SETUP.md 4.2)."
            )
        # Bound the call. Without this the SDK waits forever, and a hung
        # render is worse than a failed one: synthesize() contains a raise
        # into "publish without audio", but it can contain nothing that never
        # returns. HttpOptions.timeout is milliseconds.
        return genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(
                timeout=int(self.config.tts_timeout_seconds * 1000)
            ),
        )

    def synthesize(self, script: DialogueScript) -> Synthesized:
        """Render the dialogue, retrying once if the failure was transient.

        The attempt loop wraps the model call and the response unpacking only.
        Everything before it (the client, and therefore the API key check) and
        everything after it (an empty payload, the MP3 encode) is outside on
        purpose: none of those can come out differently a second time, and
        SPEC 6.7 classes all of them permanent.

        The shape follows `silver/table.py`'s bounded commit-race retry, which
        SPEC 7 already blesses for a transient infrastructure failure. What is
        different is the classification: that one catches a single named
        exception type, and this one has to tell a 503 apart from a bad key
        across a client library that raises neither in a form it can name.
        """
        from google.genai import types

        client = self._get_client()
        speech_config = types.SpeechConfig(
            multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                speaker_voice_configs=[
                    types.SpeakerVoiceConfig(
                        speaker="A",
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=self.config.speaker_a_voice
                            )
                        ),
                    ),
                    types.SpeakerVoiceConfig(
                        speaker="B",
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=self.config.speaker_b_voice
                            )
                        ),
                    ),
                ]
            )
        )
        max_attempts = self.config.tts_max_retries + 1
        for attempt in range(1, max_attempts + 1):
            try:
                response = client.models.generate_content(
                    model=self.config.tts_model,
                    contents=transcript(script),
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=speech_config,
                    ),
                )
                pcm = response.candidates[0].content.parts[0].inline_data.data
                break
            except Exception as exc:  # noqa: BLE001
                # Exhausted, or a failure a second attempt cannot fix. Raise
                # exactly the TTSError the caller already handles, so the
                # edition still ships without audio (SPEC 7).
                if attempt == max_attempts or not is_transient(exc):
                    raise TTSError(f"Gemini TTS call failed: {exc}") from exc
                log.warning(
                    "audio: TTS render failed transiently (attempt %d of %d), "
                    "waiting %.0fs and retrying: %s: %s",
                    attempt,
                    max_attempts,
                    self.config.tts_retry_backoff_seconds,
                    type(exc).__name__,
                    exc,
                )
                self._sleep(self.config.tts_retry_backoff_seconds)

        if not pcm:
            raise TTSError("Gemini TTS returned no audio data")

        mp3 = pcm_to_mp3(pcm)
        cost = estimate_tts_cost_usd(getattr(response, "usage_metadata", None), self.config)
        return Synthesized(
            audio_mpeg=mp3,
            duration_seconds=pcm_duration_seconds(pcm),
            cost_usd=cost,
            attempts=attempt,
        )
