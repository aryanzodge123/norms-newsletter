"""Stage: the dialogue script (SPEC 6.7). The one AI call in the audio build.

One small (Haiku-class) call turns edition.json into a two-host dialogue.
The reply is validated against audio/schema.py before anything downstream
touches it (rule zero). This mirrors the editor/writer call-validate-retry
shape in src/editor/llm.py and reuses its primitives, with one addition: the
SPEC 6.7 word band (config.audio.min_words / max_words) is a semantic accept
condition, so a script that validates structurally but lands outside the
band gets one retry that tells the model its length. If the final attempt is
still outside the band it is accepted anyway (a slightly long or short brief
is better than no audio); the caller records that it was off band.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import REPO_ROOT, AudioConfig
from ..editor import llm
from .schema import SCRIPT_SCHEMA, DialogueScript, validate_script

log = logging.getLogger(__name__)

PROMPT_VERSION = "audio_script_v1"
PROMPTS_DIR = REPO_ROOT / "prompts"
MAX_OUTPUT_TOKENS = 8192


@dataclass(frozen=True)
class ScriptResult:
    script: DialogueScript
    cost_usd: float
    within_band: bool


def load_system_prompt(prompts_dir: Path | None = None) -> str:
    """The audio-script policy, with the voice standard prepended.

    Same include pattern as the editor and silver stages: voice.md first,
    then the stage prompt.
    """
    prompts_dir = prompts_dir or PROMPTS_DIR
    voice = (prompts_dir / "voice.md").read_text()
    policy = (prompts_dir / "audio_script_v1.md").read_text()
    return f"{voice}\n\n---\n\n{policy}"


def build_user_message(edition: dict) -> str:
    """The edition as the script writer sees it. A fallback edition never
    reaches here (it carries no audio), so this is a normal/quiet edition."""
    return (
        "Write the two-host dialogue for this edition.\n\n"
        + json.dumps(edition, ensure_ascii=False, indent=2)
    )


def generate_script(
    client,
    edition: dict,
    config: AudioConfig,
    system_prompt: str,
) -> ScriptResult:
    """One script call with validation and one retry. Raises llm.AIFailure
    if no structurally valid script comes back after every attempt."""
    base_message = build_user_message(edition)
    cost = 0.0
    last_error: str | None = None
    last_valid: DialogueScript | None = None

    for attempt in range(config.max_retries + 1):
        message = base_message
        if last_error is not None:
            message = (
                f"{base_message}\n\nYour previous reply was not usable: {last_error}\n"
                "Reply with valid JSON matching the schema exactly, and keep the "
                f"dialogue between {config.min_words} and {config.max_words} words."
            )
        try:
            response = client.messages.create(
                model=config.script_model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                output_config={"format": {"type": "json_schema", "schema": SCRIPT_SCHEMA}},
                messages=[{"role": "user", "content": message}],
            )
            cost += llm.estimate_cost_usd(response.usage, config.script_model)
            text = next(block.text for block in response.content if block.type == "text")
            payload = json.loads(text)
            script = validate_script(payload)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            log.warning("audio script attempt %d failed: %s", attempt + 1, last_error)
            continue

        last_valid = script
        words = script.word_count
        if config.min_words <= words <= config.max_words:
            return ScriptResult(script=script, cost_usd=cost, within_band=True)

        # Structurally valid but off the word band. Give the model one shot
        # to fix the length, then accept it rather than losing the audio.
        last_error = f"the dialogue was {words} words, outside the target band"
        log.warning("audio script attempt %d: %s", attempt + 1, last_error)

    if last_valid is not None:
        log.warning("audio script accepted off band after retries")
        return ScriptResult(script=last_valid, cost_usd=cost, within_band=False)

    raise llm.AIFailure(
        f"audio script failed after {config.max_retries + 1} attempts: {last_error}",
        cost,
    )
