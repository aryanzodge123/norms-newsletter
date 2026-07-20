"""Edition entry point (SPEC 6.5, the 6.8 workflow's steps 2 to 5).

One run: read today's silver and bronze, decide the edition type in code,
run the editor, run the writers, run the readability gate with its one
revision pass, write edition.json, and log the run. AI failures are
contained at the smallest scope: a story loses its article, and only a
total editor failure costs the whole edition, which then publishes as a
fallback rather than not at all (decision #8).

Committing edition.json to site/content/editions/ is M5's job (SPEC 6.8
step 7). This milestone writes it to disk and stops there.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from .. import bronze, runlog
from ..config import REPO_ROOT, get_pipeline
from ..storage import get_catalog
from ..silver import table as silver_table
from . import assemble, readability, run_editor, run_writers
from .context import build_contexts
from .llm import AIFailure, get_client
from .plan import choose_edition_type, plan_sections
from .schema import SECTION_NAMES, validate_edition

log = logging.getLogger("editor")

JOB = "editor"
OUTPUT_DIR = REPO_ROOT / "site" / "content" / "editions"

# The fallback notice, in Norm's voice (SPEC section 7, DESIGN.md
# NoticeBanner). Deterministic: a fallback is often triggered by an AI
# failure, so the notice cannot itself depend on an AI call.
FALLBACK_NOTICE = (
    "Today's brief is a short one. The usual edition could not be built, so "
    "here are the stories that ranked highest, with links to the sources. "
    "Full service resumes tomorrow."
)


def _held_section_count(contexts, plan) -> int:
    """Sections that had stories but too few to run (DESIGN.md Sidebar).

    Only topics that produced exactly one usable story count as held.
    Topics with nothing were not withheld; there was nothing there.
    """
    return len(plan.held)


def _revise_for_readability(
    client, edition: dict, contexts_by_id, config, system_prompt, target_date, catalog=None
) -> tuple[dict, float, bool]:
    """SPEC 6.5's one revision pass. Returns (edition, added_cost, flag).

    Re-calls the writer only for stories over the grade limit, with their
    failing sentences listed, then re-grades. One pass: if it still fails,
    the edition publishes anyway and the boolean flag goes to the run log.
    """
    report = readability.assess(edition)
    if report.passes:
        return edition, 0.0, False

    failing = report.failing_slugs
    log.info("readability %0.2f over limit, revising %d stories", report.average, len(failing))

    # Map slug -> (section index, story index) so a revised article lands
    # back in place.
    slug_locations: dict[str, tuple[int, int]] = {}
    for si, section in enumerate(edition["sections"]):
        for ti, story in enumerate(section["stories"]):
            slug_locations[story["slug"]] = (si, ti)

    added_cost = 0.0
    for slug in failing:
        si, ti = slug_locations[slug]
        story = edition["sections"][si]["stories"][ti]
        if story["article"] is None:
            continue  # a collapsed card has only a summary; nothing to revise
        context = contexts_by_id.get(story["cluster_id"])
        if context is None:
            continue
        failing_sentences = readability.failing_sentences(
            readability.revisable_text(story)
        )
        result = run_writers.write_one(
            client, context, config, system_prompt, target_date, failing_sentences, catalog
        )
        added_cost += result.cost_usd
        if result.article is not None:
            story["article"] = result.article

    validate_edition(edition)
    report = readability.assess(edition)
    if not report.passes:
        log.warning(
            "readability still %0.2f after revision, publishing and flagging",
            report.average,
        )
    return edition, added_cost, not report.passes


def run(target_date: date | None = None, *, dry_run: bool = False) -> int:
    """One edition cycle. Returns the process exit code."""
    run_id = runlog.make_run_id()
    started_at = datetime.now(UTC)
    config = get_pipeline().editor
    ingest_date = target_date or started_at.date()

    catalog = get_catalog()
    bronze_items = bronze.read_partition(bronze.ensure_table(catalog), ingest_date)
    silver_rows = silver_table.read_partition(silver_table.ensure_table(catalog), ingest_date)

    contexts = build_contexts(silver_rows, bronze_items)
    edition_type = choose_edition_type(contexts, config)
    plan = plan_sections(contexts)

    # SPEC 6.9 drops the day's bronze and silver partitions once the archival
    # job has folded them into gold, so any re-run of an already-published
    # date sees an empty day. Without this guard the re-run would replace a
    # real edition with an empty fallback, which is the opposite of what
    # decision #17 means by "the committed editions are the publication
    # record". An already-published date with nothing left to read keeps what
    # it published.
    existing = OUTPUT_DIR / f"{ingest_date.isoformat()}.json"
    if not contexts and existing.exists():
        log.info(
            "no usable clusters for %s and %s already exists (its partitions "
            "were archived); keeping the published edition",
            ingest_date,
            existing.name,
        )
        return 0

    log.info(
        "run %s: %d items, %d clusters, %d usable -> %s edition",
        run_id,
        len(bronze_items),
        len(silver_rows),
        len(contexts),
        edition_type,
    )

    if dry_run:
        print(f"\nrun_id {run_id} (dry run, no AI calls, nothing written)")
        print(f"  {ingest_date}: {edition_type} edition")
        print(f"  {len(contexts)} usable clusters, sections available: "
              f"{', '.join(plan.available) or 'none'}")
        if plan.held:
            print(f"  sections held (to briefly): {', '.join(plan.held)}")
        for context in contexts[:20]:
            grounded = "article" if context.grounding_chars >= config.min_grounding_chars else "collapsed"
            print(f"  [{context.score}] {SECTION_NAMES.get(context.topic, context.topic)}: "
                  f"{context.headline[:60]} ({grounded})")
        return 0

    cost = 0.0
    status = "success"
    notes: list[str] = []
    readability_flag = False
    edition: dict | None = None
    client = None

    try:
        client = get_client()
        contexts_by_id = {c.cluster_id: c for c in contexts}

        if edition_type == "fallback":
            edition = assemble.assemble_fallback(
                contexts=contexts, target_date=ingest_date, notice=FALLBACK_NOTICE
            )
            status = "partial"
            notes.append("fallback edition: too little usable data for a normal or quiet day")
        else:
            editor_system = run_editor.load_system_prompt()
            writer_system = run_writers.load_system_prompt()
            try:
                editor_call = run_editor.run_editor(
                    client, contexts, edition_type, plan, config, editor_system
                )
                cost += editor_call.cost_usd
            except AIFailure as failure:
                cost += failure.cost_usd
                log.error("editor failed twice, publishing fallback: %s", failure)
                edition = assemble.assemble_fallback(
                    contexts=contexts, target_date=ingest_date, notice=FALLBACK_NOTICE
                )
                status = "partial"
                notes.append("fallback edition: editor output invalid twice (SPEC 7)")
            else:
                selected_ids = {
                    story.cluster_id
                    for section in editor_call.value.sections
                    for story in section.stories
                }
                selected = [c for c in contexts if c.cluster_id in selected_ids]
                articles = run_writers.run_writers(
                    client, selected, config, writer_system, ingest_date, catalog=catalog
                )
                cost += sum(result.cost_usd for result in articles.values())

                edition = assemble.assemble_edition(
                    editor=editor_call.value,
                    articles=articles,
                    contexts=contexts,
                    edition_type=edition_type,
                    target_date=ingest_date,
                    items_ingested=len(bronze_items),
                    clusters_considered=len(silver_rows),
                    sections_held=_held_section_count(contexts, plan),
                )

                skipped = sum(1 for r in articles.values() if r.status == "skipped_grounding")
                failed = sum(1 for r in articles.values() if r.status == "failed_validation")
                if skipped:
                    notes.append(f"{skipped} stories published without an article (thin grounding)")
                if failed:
                    notes.append(f"{failed} stories' articles failed validation twice")
                if skipped or failed:
                    status = "partial"

                edition, revision_cost, readability_flag = _revise_for_readability(
                    client, edition, contexts_by_id, config, writer_system, ingest_date, catalog
                )
                cost += revision_cost
                if readability_flag:
                    status = "partial"
                    notes.append("readability gate exceeded after revision (SPEC 6.5)")

        written = _write_edition(edition, ingest_date)
        log.info("wrote %s (%s), est $%.4f", written, edition_type, cost)

    except Exception as exc:  # noqa: BLE001
        status = "failed"
        notes.append(f"edition run failed: {type(exc).__name__}: {exc}")
        log.error(notes[-1])
        edition = None
    finally:
        _log_run(
            run_id=run_id,
            started_at=started_at,
            status=status,
            items_in=len(bronze_items),
            items_out=len(silver_rows),
            cost=cost,
            readability_flag=readability_flag,
            notes="; ".join(notes) or None,
        )

    return 1 if status == "failed" else 0


def _write_edition(edition: dict, ingest_date: date) -> Path:
    """Write edition.json to disk (SPEC 6.8 step 7 commits it; not here)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{ingest_date.isoformat()}.json"
    path.write_text(json.dumps(edition, indent=2, ensure_ascii=False) + "\n")
    return path


def _log_run(
    *, run_id, started_at, status, items_in, items_out, cost, readability_flag, notes
) -> None:
    try:
        runlog.write_row(
            runlog.ensure_table(get_catalog()),
            runlog.build_row(
                run_id=run_id,
                job=JOB,
                started_at=started_at,
                ended_at=datetime.now(UTC),
                status=status,
                items_in=items_in,
                items_out=items_out,
                ai_cost_estimate_usd=round(cost, 6),
                readability_flag=readability_flag,
                notes=notes,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        log.error("could not write run_log row: %s", exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Norm's Newsletter edition stage")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="plan the edition and print, make no AI calls, write nothing",
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        help="re-run a past ingest_date, YYYY-MM-DD (default today)",
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
