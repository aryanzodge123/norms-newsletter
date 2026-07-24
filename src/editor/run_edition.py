"""Edition entry point (SPEC 6.5, the 6.8 workflow's steps 2 to 5).

One run: read today's silver and bronze, decide the edition type in code,
run the editor, run the writers, run the readability gate with its one
revision pass, write edition.json, and log the run. AI failures are
contained at the smallest scope: a story loses its article, and only a
total editor failure costs the whole edition, which then publishes as a
fallback rather than not at all (decision #8).

Decision #26 makes that a floor rather than a best effort. Once there are
contexts, every path out of this module writes an edition, in two tiers.
A stage that has not produced an edition yet (the editor, the writers,
assembly) degrades to the fallback. A stage that already holds a validated
edition (the readability revision) publishes it unrevised, because the
fallback would be strictly worse than what is already in hand.

Committing edition.json to site/content/editions/ is M5's job (SPEC 6.8
step 7). This milestone writes it to disk and stops there.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from .. import bronze, runlog
from ..config import REPO_ROOT, get_pipeline
from ..storage import get_catalog
from ..silver import table as silver_table
from . import assemble, headline_gate, readability, run_editor, run_writers, simplify
from .context import build_contexts, retrieve_prior_mentions_batch
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


def simplify_prompt() -> str:
    """The readability-revision policy, voice standard prepended. Same
    include pattern as every other stage."""
    prompts_dir = REPO_ROOT / "prompts"
    voice = (prompts_dir / "voice.md").read_text()
    policy = (prompts_dir / "simplify_v1.md").read_text()
    return f"{voice}\n\n---\n\n{policy}"


def _held_section_count(contexts, plan) -> int:
    """Sections that had stories but too few to run (DESIGN.md Sidebar).

    Only topics that produced exactly one usable story count as held.
    Topics with nothing were not withheld; there was nothing there.
    """
    return len(plan.held)


def _revise_for_readability(
    client, edition: dict, contexts_by_id, config, system_prompt, target_date,
    catalog=None, prior_mentions=None,
) -> tuple[dict, float, bool]:
    """SPEC 6.5's revision pass. Returns (edition, added_cost, flag).

    Each pass simplifies the editor-owned text that reads too hard, then
    re-calls the writer for the stories that are themselves over the limit,
    with their hardest sentences listed. It repeats until the edition is
    under the limit or `readability_max_passes` is spent, then publishes
    either way: availability beats perfection, and a still-hard edition sets
    the run-log flag (SPEC 6.5).

    SPEC 6.5 describes "one automatic revision pass". One pass reliably lands
    just over the line on real editions (11.3 to 9.15 measured), so the pass
    count is a config value defaulting to 2. That is a proposed SPEC 6.5
    amendment, logged in MILESTONES.md.
    """
    added_cost = 0.0
    simplify_system = simplify_prompt()

    for attempt in range(config.readability_max_passes):
        report = readability.assess(edition)
        if report.passes:
            break

        failing = report.failing_slugs
        log.info(
            "readability %0.2f over limit (pass %d of %d), revising %d stories",
            report.average,
            attempt + 1,
            config.readability_max_passes,
            len(failing),
        )

        # Map slug -> (section index, story index) so a revised article lands
        # back in place.
        slug_locations: dict[str, tuple[int, int]] = {}
        for si, section in enumerate(edition["sections"]):
            for ti, story in enumerate(section["stories"]):
                slug_locations[story["slug"]] = (si, ti)

        # The editor's own text is measured by the gate but used to be
        # unrevisable: only writers were re-called. On real editions the
        # editor's lines graded worst (summaries 17.0, glance 14.3, against
        # articles at 11.5), so an edition could not get under the limit
        # however well the articles were rewritten.
        _, simplify_cost = simplify.simplify_edition(
            client, edition, config, simplify_system
        )
        added_cost += simplify_cost

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
                client, context, config, system_prompt, target_date,
                failing_sentences, catalog, prior_mentions,
            )
            added_cost += result.cost_usd
            if result.article is not None:
                story["article"] = result.article

        validate_edition(edition)

    report = readability.assess(edition)
    if not report.passes:
        log.warning(
            "readability still %0.2f after %d passes, publishing and flagging",
            report.average,
            config.readability_max_passes,
        )
    return edition, added_cost, not report.passes


def _run_headline_gate(
    *, client, editor_call, contexts, edition_type, plan, config,
    editor_system, prior_coverage, target_date,
):
    """SPEC 6.5's headline repetition gate. Returns (call, flag, added_cost).

    One retry naming the offending headline, then publish either way. The
    readability gate has the same posture (line ~137): availability beats
    perfection, and a repeated headline is a quality defect rather than a
    correctness one. Failing an edition over it would be a worse trade.

    A retry that itself fails validation keeps the first response rather
    than costing the edition, so the gate can only ever change the headline
    or flag it, never remove the newsletter.

    The whole body is wrapped for the same reason. This runs inside
    run()'s try, where an unhandled exception sets edition = None and skips
    _write_edition, publishing nothing at all. A quality check must never be
    able to do that, which is the same reasoning that kept the headline rule
    off the Edition validator (decision #25). If the gate itself breaks, the
    edition ships with the headline the editor wrote.
    """
    try:
        return _headline_gate_inner(
            client=client, editor_call=editor_call, contexts=contexts,
            edition_type=edition_type, plan=plan, config=config,
            editor_system=editor_system, prior_coverage=prior_coverage,
            target_date=target_date,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("headline gate failed, publishing the editor's headline: %s", exc)
        return editor_call, False, 0.0


def _headline_gate_inner(
    *, client, editor_call, contexts, edition_type, plan, config,
    editor_system, prior_coverage, target_date,
):
    pipeline = get_pipeline()
    archive_cfg = pipeline.archive
    prior = headline_gate.recent_headlines(
        target_date, archive_cfg.continuing_coverage_lookback_days
    )
    if not prior:
        return editor_call, False, 0.0

    def _verdict(call):
        return headline_gate.check(
            call.value.headline_of_the_day,
            prior,
            threshold=archive_cfg.headline_repeat_threshold,
            model_name=pipeline.silver.embedding_model,
            prior_coverage=prior_coverage.get(call.value.headline_cluster_id, []),
        )

    result = _verdict(editor_call)
    if not result.repeated:
        return editor_call, False, 0.0

    log.warning(
        "headline restates %s (%.3f), asking the editor for the new development",
        result.prior.date,
        result.similarity,
    )

    added = 0.0
    try:
        retry = run_editor.run_editor(
            client, contexts, edition_type, plan, config, editor_system,
            prior_coverage=prior_coverage,
            repeat_feedback=result.feedback(),
        )
    except AIFailure as failure:
        # The retry was invalid twice. Keep the first, valid response: a
        # duplicate headline is better than no edition (SPEC section 7).
        log.warning("headline retry failed validation, keeping the first response")
        return editor_call, True, failure.cost_usd

    added += retry.cost_usd
    if _verdict(retry).repeated:
        log.warning("headline still repeats after one retry, publishing and flagging")
        return retry, True, added
    return retry, False, added


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
    headline_repeat_flag = False
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

            # Computed once, before the editor call, and shared with the
            # writer stage and every readability pass (SPEC 6.5). This used
            # to run per story inside write_one, so a twelve-story edition
            # scanned gold a dozen times over nearly the same rows.
            archive_cfg = get_pipeline().archive
            try:
                prior_coverage = retrieve_prior_mentions_batch(
                    contexts,
                    ingest_date,
                    catalog,
                    lookback_days=archive_cfg.continuing_coverage_lookback_days,
                )
            except Exception as exc:  # noqa: BLE001
                # Gold being unreachable must not cost the edition. Without
                # the map the editor simply works as it did before this
                # feature existed, and the gate stays quiet.
                log.warning("continuing-coverage lookup failed, continuing: %s", exc)
                prior_coverage = {}
            if prior_coverage:
                log.info(
                    "%d of %d candidates continue a recently published story",
                    len(prior_coverage),
                    len(contexts),
                )

            try:
                editor_call = run_editor.run_editor(
                    client, contexts, edition_type, plan, config, editor_system,
                    prior_coverage=prior_coverage,
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
                editor_call, headline_repeat_flag, gate_cost = _run_headline_gate(
                    client=client,
                    editor_call=editor_call,
                    contexts=contexts,
                    edition_type=edition_type,
                    plan=plan,
                    config=config,
                    editor_system=editor_system,
                    prior_coverage=prior_coverage,
                    target_date=ingest_date,
                )
                cost += gate_cost
                if headline_repeat_flag:
                    status = "partial"
                    notes.append("headline repeated a recent edition (SPEC 6.5)")

                # Tier one of decision #26. Nothing between here and the end
                # of assembly holds an edition yet, so the only recovery is
                # the fallback. assemble_edition raises when the editor names
                # a cluster it was not offered, or when the assembled object
                # misses the canonical schema; structured output constrains
                # the model's shape, not its values, so both stay reachable.
                # Without this the outer handler nulls the edition and skips
                # _write_edition, publishing nothing at all (SPEC section 7).
                try:
                    selected_ids = {
                        story.cluster_id
                        for section in editor_call.value.sections
                        for story in section.stories
                    }
                    selected = [c for c in contexts if c.cluster_id in selected_ids]
                    articles = run_writers.run_writers(
                        client, selected, config, writer_system, ingest_date,
                        catalog=catalog, prior_mentions=prior_coverage,
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
                except Exception as exc:  # noqa: BLE001
                    log.error("edition assembly failed, publishing fallback: %s", exc)
                    edition = assemble.assemble_fallback(
                        contexts=contexts, target_date=ingest_date, notice=FALLBACK_NOTICE
                    )
                    status = "partial"
                    notes.append(
                        f"fallback edition: {type(exc).__name__} during assembly ({exc})"
                    )
                    edition_type = "fallback"
                else:
                    # Tier two, and only on the path that actually produced a
                    # normal or quiet edition. A fallback has no sections to
                    # measure or revise. Measured: it survives the revision
                    # today, because readability.assess finds nothing failing
                    # and the loop never runs. That is luck, not design, so
                    # the else keeps the fallback out rather than relying on
                    # it.
                    #
                    # From here an edition exists and has already passed
                    # validate_edition, so the fallback would be a downgrade
                    # rather than a rescue. The copy is what makes that
                    # recovery safe: simplify_edition and the per-story loop
                    # both rewrite the edition in place, so a raise partway
                    # through can leave the live object half revised.
                    pristine = copy.deepcopy(edition)
                    try:
                        edition, revision_cost, readability_flag = _revise_for_readability(
                            client, edition, contexts_by_id, config, writer_system,
                            ingest_date, catalog, prior_coverage,
                        )
                        cost += revision_cost
                    except Exception as exc:  # noqa: BLE001
                        log.error(
                            "readability revision failed, publishing as assembled: %s", exc
                        )
                        edition = pristine
                        readability_flag = True
                        notes.append(
                            f"readability revision raised {type(exc).__name__}: {exc}"
                        )
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
            headline_repeat_flag=headline_repeat_flag,
            notes="; ".join(notes) or None,
        )

    return 1 if status == "failed" else 0


def _write_edition(edition: dict, ingest_date: date) -> Path:
    """Write edition.json to disk (SPEC 6.8 step 7 commits it; not here).

    A fallback never replaces an already published normal or quiet edition
    for the same date (decision #17, SPEC section 7). The guard at the top
    of run() only covers a re-run whose partitions were already archived;
    a re-run that still has its data would rebuild, and any of the failures
    decision #26 catches would then overwrite a good page with a link list.
    Checked here rather than at each fallback site so the editor-failure
    path gets it too.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{ingest_date.isoformat()}.json"
    if edition.get("edition_type") == "fallback" and path.exists():
        try:
            published = json.loads(path.read_text()).get("edition_type")
        except (OSError, ValueError):
            # An unreadable file is not a publication record worth keeping.
            published = None
        if published in ("normal", "quiet"):
            log.warning(
                "%s already holds a %s edition; keeping it rather than "
                "overwriting with a fallback (decision #17)",
                path.name,
                published,
            )
            return path
    path.write_text(json.dumps(edition, indent=2, ensure_ascii=False) + "\n")
    return path


def _log_run(
    *, run_id, started_at, status, items_in, items_out, cost, readability_flag,
    headline_repeat_flag, notes,
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
