"""The `site` run_log row: when the edition actually went live (SPEC 6.11).

SPEC section 8 says run_log holds one row per job run, written by every job,
and lists `site` among them. Nothing wrote that row until this module: the
publish workflow deployed the site and moved on, so the one timestamp that
says "readers can now read today's edition" existed only in GitHub's run
history and not in the data the weekly review reads.

That gap is what made section 8's timeliness measure unimplementable, since it
is defined against this row's `ended_at`. The step runs immediately after the
healthchecks ping, so the row closes once the deploy has succeeded and the
dead man's switch is green. `ended_at` is therefore the moment the site was
live, which is exactly what "late" should be measured against.

The row also carries the triggering event in `notes` as `trigger=<event>`.
That single field answers two questions: which scheduler published today
(6.11's whole point, since a dead external trigger is otherwise invisible),
and section 13's amended migration exit criterion, which requires proving a
publish was dispatch-triggered rather than cron-triggered.

The trigger arrives as a CLI argument rather than an environment variable
because `src/config.py` is the only module permitted to read the environment
(SPEC 6.10).

Writes one run_log row. Makes no AI calls and touches no edition file.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from . import runlog

log = logging.getLogger("site_run")

JOB = "site"

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITIONS_DIR = REPO_ROOT / "site" / "content" / "editions"


def edition_path(target_date: date) -> Path:
    return EDITIONS_DIR / f"{target_date.isoformat()}.json"


def story_count(edition: dict) -> int:
    """Cards published across all sections.

    Briefly lines are deliberately not counted. `items_out` here means "how
    many stories got a card", which is the number the weekly review compares
    against the 15-20 budget (decision #3). Briefly coverage is counted where
    it matters, in gold retrieval (SPEC 6.9, decision #23).
    """
    return sum(len(section.get("stories", [])) for section in edition.get("sections", []))


def run(
    target_date: date | None = None,
    *,
    trigger: str | None = None,
    dry_run: bool = False,
) -> int:
    """Record one `site` run. Returns the process exit code."""
    with runlog.logged_run(JOB, dry_run=dry_run) as rec:
        edition_date = target_date or rec.started_at.date()

        # Recorded first, so the trigger is on the row even if the edition
        # lookup below goes wrong. Knowing which scheduler fired is useful
        # precisely on the days something else failed.
        rec.note(f"trigger={trigger or 'unknown'}")

        path = edition_path(edition_date)
        if not path.exists():
            # The deploy happened but this date has no edition file. Not this
            # module's job to fix or to fail the publish over: record it and
            # let the missing healthcheck ping be the alarm (SPEC section 8).
            log.warning("no edition at %s; recording the run anyway", path)
            rec.status = "partial"
            rec.reason(runlog.REASON_NO_EDITION)
            rec.note("no edition.json for this date")
        else:
            edition = json.loads(path.read_text())
            rec.items_in = 1
            rec.items_out = story_count(edition)
            rec.note(f"edition_type={edition.get('edition_type', 'unknown')}")
            log.info(
                "site run for %s: %d stories, trigger=%s",
                edition_date,
                rec.items_out,
                trigger or "unknown",
            )

        if dry_run:
            print(f"run_id {rec.run_id} (dry run, no row written)")
            print(f"  {edition_date}: {'; '.join(rec.notes)}")

    return 1 if rec.status == "failed" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record the site run_log row (SPEC 6.11, section 8)"
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        help="record a past run_date, YYYY-MM-DD (default today)",
    )
    parser.add_argument(
        "--trigger",
        help="the GitHub event that started the publish (github.event_name)",
    )
    parser.add_argument("--dry-run", action="store_true", help="write no row")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    return run(args.date, trigger=args.trigger, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
