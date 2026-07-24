"""Audio build entry point (SPEC 6.7, the 6.8 workflow's step 6).

One run: read the committed edition.json for a date, write a two-host
dialogue (the one AI call), synthesize it to MP3, upload the MP3 to R2, and
inject the audio block back into edition.json so the commit and the site
build carry it. Every failure is contained to "publish without an audio
row" (SPEC 7): a missing edition, a fallback edition, a script that fails
twice, a TTS failure, or an upload failure all leave audio null and never
break the publish.

Deterministic everywhere except generate_script: TTS, duration, size,
upload, and the audio block are code (rule zero).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from .. import runlog
from ..config import REPO_ROOT, get_pipeline
from ..editor.llm import AIFailure, get_client
from ..editor.schema import validate_edition
from ..storage import (
    AudioStorageError,
    audio_object_exists,
    audio_public_url,
    get_catalog,
    upload_audio,
)
from . import script as script_stage
from .schema import DialogueScript
from .tts import GeminiSynthesizer, Synthesized, TTSError

log = logging.getLogger("audio")

JOB = "audio"
EDITIONS_DIR = REPO_ROOT / "site" / "content" / "editions"


@dataclass
class AudioResult:
    audio: dict | None
    cost_usd: float
    turns: int
    note: str


def audio_key(edition_date: str) -> str:
    """The R2 object key for a date (SPEC 6.7: /audio/YYYY-MM-DD.mp3)."""
    return f"audio/{edition_date}.mp3"


def edition_path(target_date: date) -> Path:
    return EDITIONS_DIR / f"{target_date.isoformat()}.json"


def build_audio(
    edition: dict,
    config,
    *,
    client,
    synthesizer=None,
    upload=upload_audio,
    exists=audio_object_exists,
    public_url=audio_public_url,
    dry_run: bool = False,
) -> AudioResult:
    """Produce the audio block for one edition, or None on any contained
    failure. Pure of run_log/IO except the injected upload, so tests drive
    it with a fake synthesizer and a fake upload."""
    if edition.get("edition_type") == "fallback":
        return AudioResult(None, 0.0, 0, "fallback edition carries no audio")

    # A date's MP3 is written once. If this edition already carries an audio
    # block and the object is still in the bucket, re-derive the URL from the
    # current configuration and keep the measurements, rather than paying for
    # a second script call and a second TTS render. This is what makes a
    # re-publish cheap, and it is also how a corrected public base URL reaches
    # an already-voiced edition.
    key = audio_key(edition["date"])
    existing = edition.get("audio")
    if existing and not dry_run and exists(key):
        refreshed = {
            "url": public_url(key),
            "duration_seconds": existing["duration_seconds"],
            "size_bytes": existing["size_bytes"],
        }
        note = "reused the MP3 already in R2"
        if refreshed["url"] != existing.get("url"):
            note += f" (url refreshed to {refreshed['url']})"
        return AudioResult(refreshed, 0.0, 0, note)

    system_prompt = script_stage.load_system_prompt()
    try:
        result = script_stage.generate_script(client, edition, config, system_prompt)
    except AIFailure as failure:
        return AudioResult(None, failure.cost_usd, 0, f"script failed twice: {failure}")

    turns = len(result.script.turns)
    band_note = "" if result.within_band else " (off word band)"

    if dry_run:
        return AudioResult(
            None,
            result.cost_usd,
            turns,
            f"dry run: {result.script.word_count} words, {turns} turns{band_note}, "
            "no TTS or upload",
        )

    synthesizer = synthesizer or GeminiSynthesizer(config)
    try:
        rendered: Synthesized = synthesizer.synthesize(result.script)
    except TTSError as exc:
        return AudioResult(None, result.cost_usd, turns, f"TTS failed: {exc}")

    # The TTS render was paid for the moment synthesize() returned, so its
    # cost counts even if the upload then fails.
    total_cost = result.cost_usd + rendered.cost_usd

    try:
        url = upload(key, rendered.audio_mpeg)
    except AudioStorageError as exc:
        return AudioResult(None, total_cost, turns, f"upload failed: {exc}")

    audio = {
        "url": url,
        "duration_seconds": rendered.duration_seconds,
        "size_bytes": rendered.size_bytes,
    }
    return AudioResult(
        audio,
        total_cost,
        turns,
        f"audio {rendered.duration_seconds}s, {rendered.size_bytes} bytes{band_note} "
        f"(script ${result.cost_usd:.4f} + tts ${rendered.cost_usd:.4f})",
    )


def inject_audio(edition: dict, audio: dict | None) -> dict:
    """Set the audio block and re-validate. The block is deterministic code,
    so the edition must still be a valid SPEC 6.5 edition afterward."""
    edition["audio"] = audio
    validate_edition(edition)
    return edition


def run(target_date: date | None = None, *, dry_run: bool = False) -> int:
    """One audio cycle. Returns the process exit code."""
    with runlog.logged_run(JOB, dry_run=dry_run) as rec:
        config = get_pipeline().audio
        edition_date = target_date or rec.started_at.date()

        # Parsing edition.json used to sit outside the try, so a corrupt
        # edition raised JSONDecodeError straight out of run() with no row and
        # a non-zero crash that, before the workflow fix, killed the deploy.
        path = edition_path(edition_date)
        if not path.exists():
            log.warning("no edition at %s; nothing to voice", path)
            rec.status = "partial"
            rec.note("no edition.json for this date")
            return 1 if rec.status == "failed" else 0

        edition = json.loads(path.read_text())

        # The script call runs even on a dry run: inspecting the generated
        # dialogue and its length is the point of it. Only TTS and the upload
        # (the cost and the side effects) are skipped. The editor stage's own
        # dry run makes no AI call; audio differs because the script is the
        # thing being checked.
        client = get_client()
        result = build_audio(edition, config, client=client, dry_run=dry_run)
        rec.items_in = result.turns
        rec.items_out = 1 if result.audio else 0
        rec.ai_cost_estimate_usd = round(result.cost_usd, 6)
        if result.note:
            rec.note(result.note)

        if dry_run:
            print(f"\nrun_id {rec.run_id} (dry run, no TTS, nothing written)")
            print(f"  {edition_date}: {result.note}")
            return 0

        if edition.get("edition_type") == "fallback":
            # A fallback edition has no audio field at all (FallbackEdition
            # forbids it, SPEC 6.5), so there is nothing to inject and injecting
            # audio=None would fail schema validation. build_audio already bowed
            # out with the fallback note; treat it as a contained no-op, leave
            # the file untouched, and let the publish proceed without an audio
            # row (SPEC 7).
            rec.status = "partial"
        else:
            if result.audio is None:
                # A contained failure. The edition still publishes, no audio.
                rec.status = "partial"
            inject_audio(edition, result.audio)
            path.write_text(json.dumps(edition, indent=2, ensure_ascii=False) + "\n")
        log.info("%s: %s (est $%.4f)", edition_date, result.note, result.cost_usd)
    return 1 if rec.status == "failed" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Norm's Newsletter audio build")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="write the script and print its length, make no TTS call, write nothing",
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        help="voice a past edition, YYYY-MM-DD (default today)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    return run(args.date, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
