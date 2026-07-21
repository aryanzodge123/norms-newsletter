"""Text to speech (SPEC 6.7, decision #4).

Multi-speaker TTS behind a swappable interface. The default backend is
Gemini multi-speaker TTS; swapping it is a config change (audio.tts_model,
the two voice names) plus a new Synthesizer, not a change to the caller.

The interface returns the encoded MP3 together with its exact duration.
Duration is computed from the raw PCM sample count before encoding, so it is
exact and needs no MP3 parsing; size is just the length of the encoded
bytes. A backend that cannot produce audio raises TTSError, which the caller
turns into "publish without an audio row" (SPEC 7).
"""

from __future__ import annotations

import logging
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

    def __init__(self, config: AudioConfig, *, client=None) -> None:
        self.config = config
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        from google import genai

        settings = get_settings()
        if not settings.gemini_api_key:
            raise TTSError(
                "GEMINI_API_KEY is required for audio synthesis. Set it in .env "
                "locally or as an Actions secret in CI (SETUP.md 4.2)."
            )
        return genai.Client(api_key=settings.gemini_api_key)

    def synthesize(self, script: DialogueScript) -> Synthesized:
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
        except Exception as exc:  # noqa: BLE001
            raise TTSError(f"Gemini TTS call failed: {exc}") from exc

        if not pcm:
            raise TTSError("Gemini TTS returned no audio data")

        mp3 = pcm_to_mp3(pcm)
        cost = estimate_tts_cost_usd(getattr(response, "usage_metadata", None), self.config)
        return Synthesized(
            audio_mpeg=mp3,
            duration_seconds=pcm_duration_seconds(pcm),
            cost_usd=cost,
        )
