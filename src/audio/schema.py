"""The dialogue-script schema (SPEC 6.7), written before the prompt.

Rule zero (SPEC section 2): the one AI call in the audio build outputs
schema-validated JSON only. This module, not the prompt, is the authority
on what a valid script is. TTS, duration, upload and the audio block are
all deterministic code downstream of a validated script.

SPEC 6.7: "one small model call turns edition.json into a two-host dialogue
(hosts define terms to each other; 1,300-1,600 words)." The two-host shape
and the em-dash ban live here as validators. The word band is a config
value (config.audio.min_words / max_words), so it is checked by the caller
against a validated script rather than hardcoded in the schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

# Two hosts, named by the design. The renderer and the TTS voices map onto
# these two labels; a third speaker is not a valid two-host dialogue.
SPEAKERS = ("A", "B")

EM_DASH = "—"


class ScriptInvalid(ValueError):
    """Raised when an object is not a valid dialogue script."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _no_em_dash(value: str) -> str:
    if EM_DASH in value:
        raise ValueError("em dash is not allowed in generated text (voice standard 8)")
    return value


class Turn(Strict):
    """One host's line."""

    speaker: Literal["A", "B"]
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def _clean(cls, value: str) -> str:
        return _no_em_dash(value.strip())


class DialogueScript(Strict):
    """A two-host dialogue (SPEC 6.7)."""

    turns: list[Turn] = Field(min_length=4)

    @model_validator(mode="after")
    def _both_hosts_speak(self) -> DialogueScript:
        present = {turn.speaker for turn in self.turns}
        if present != set(SPEAKERS):
            raise ValueError(
                f"a two-host dialogue needs both speakers {list(SPEAKERS)}, got {sorted(present)}"
            )
        return self

    @property
    def word_count(self) -> int:
        return sum(len(turn.text.split()) for turn in self.turns)


def validate_script(obj: dict) -> DialogueScript:
    """Validate one script object. Raises ScriptInvalid on anything bad."""
    if not isinstance(obj, dict):
        raise ScriptInvalid(f"script must be a JSON object, got {type(obj).__name__}")
    try:
        return DialogueScript(**obj)
    except ValidationError as exc:
        raise ScriptInvalid(f"script failed schema validation: {exc}") from exc


# Reuse the editor stage's transform so the API-schema rules (inline $defs,
# additionalProperties: false, strip unsupported value constraints) live in
# exactly one place and cannot drift between stages.
from ..editor.schema import _api_schema  # noqa: E402

SCRIPT_SCHEMA = _api_schema(DialogueScript)
