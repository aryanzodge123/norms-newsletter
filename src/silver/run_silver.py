"""Silver entry point (SPEC 6.4).

One run: read today's bronze, dedup, embed, cluster, score what is new or
grown, overwrite the partition, log the run.

Idempotent by rebuild. Running this twice over the same bronze data costs
one embedding pass and zero AI calls the second time, because every
cluster is unchanged and its score carries forward (decision #6).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from .. import bronze, runlog
from ..config import REPO_ROOT, get_pipeline
from ..storage import get_catalog
from . import cluster as clustering
from . import score as scoring
from . import table as silver_table
from .dedup import dedup

log = logging.getLogger("silver")

JOB = "silver"
PROMPTS_DIR = REPO_ROOT / "prompts"


def load_system_prompt(prompts_dir: Path | None = None) -> str:
    """The scoring rubric, with the voice standard prepended.

    CLAUDE.md requires every prompt to include prompts/voice.md. Scoring
    emits almost no prose, but the one-sentence rationale is still text
    the project owns, and keeping the include uniform means no prompt has
    to remember to opt in.
    """
    prompts_dir = prompts_dir or PROMPTS_DIR
    voice = (prompts_dir / "voice.md").read_text()
    rubric = (prompts_dir / "scoring_v1.md").read_text()
    return f"{voice}\n\n---\n\n{rubric}"


def carry_forward(previous: dict, cluster: clustering.Cluster) -> scoring.ScoringResult | None:
    """Reuse a stored score when the cluster has not changed.

    Decision #6, incremental scoring: re-score only new clusters and
    clusters whose member count changed. A cluster that gained a source
    may read differently, so it is scored again; one that did not is not.
    A stored null score is not carried forward, because a retry on the
    next run is exactly what we want.
    """
    stored = previous.get(cluster.cluster_id)
    if stored is None:
        return None
    if stored["member_count"] != len(cluster.members):
        return None
    if stored["score"] is None:
        return None
    return scoring.ScoringResult(
        score=stored["score"],
        topic=stored["topic"],
        rationale=stored["rationale"],
        confidence=stored["confidence"],
        model_version=stored["model_version"],
        prompt_version=stored["prompt_version"],
        scored_at=stored["scored_at"],
        cost_usd=0.0,
    )


def build_clusters(items, config) -> list[clustering.Cluster]:
    """Dedup, embed, cluster. The deterministic half of the run."""
    kept = dedup(items)
    if not kept:
        return []
    texts = [clustering.embed_text(item, config.embed_chars) for item in kept]
    embeddings = clustering.embed(texts, config.embedding_model)
    return clustering.cluster(kept, embeddings, config.cluster_threshold)


def run(target_date: date | None = None, *, dry_run: bool = False) -> int:
    """One silver cycle. Returns the process exit code."""
    with runlog.logged_run(JOB, dry_run=dry_run) as rec:
        config = get_pipeline().silver
        ingest_date = target_date or rec.started_at.date()

        # Catalog connect, bronze read, and the whole scoring loop used to run
        # outside the try whose finally logged the row, so any failure there
        # (an unreachable catalog most likely) left no row (SPEC section 8).
        catalog = get_catalog()
        items = bronze.read_partition(bronze.ensure_table(catalog), ingest_date)
        rec.items_in = len(items)
        log.info("run %s: %d bronze items for %s", rec.run_id, len(items), ingest_date)

        clusters = build_clusters(items, config)

        if dry_run:
            print(f"\nrun_id {rec.run_id} (dry run, no AI calls, nothing written)")
            print(f"  {len(items)} items -> {len(clusters)} clusters for {ingest_date}\n")
            for c in sorted(clusters, key=lambda c: -len(c.members))[:15]:
                print(f"  [{len(c.members)}] {c.seed.title[:72]}")
                if len(c.members) > 1:
                    for other in c.members[1:]:
                        print(f"      + {other.source}: {other.title[:64]}")
            return 0

        table = silver_table.ensure_table(catalog)
        previous = silver_table.read_partition(table, ingest_date)

        rows: list[dict] = []
        cost = 0.0
        scored = 0
        null_scores = 0
        client = None
        system_prompt = load_system_prompt()

        for c in clusters:
            result = carry_forward(previous, c)
            if result is None:
                if client is None:
                    client = scoring.get_client()
                    scoring.ensure_cacheable(client, system_prompt, config.scoring_model)
                result = scoring.score_cluster(client, c, config, system_prompt)
                scored += 1
                cost += result.cost_usd
                if result.is_null_score:
                    null_scores += 1
            rows.append(silver_table.build_row(c, result))

        rec.ai_cost_estimate_usd = round(cost, 6)
        if null_scores:
            rec.status = "partial"
        log.info(
            "scored %d of %d clusters (%d carried forward), %d null, est $%.4f",
            scored,
            len(clusters),
            len(clusters) - scored,
            null_scores,
            cost,
        )

        # Kept as an inner try so the write failure keeps its specific note.
        # The outer logged_run would still catch it, but with a generic
        # message; this preserves the diagnostic wording.
        try:
            rec.items_out = silver_table.overwrite_partition(table, ingest_date, rows)
            if null_scores:
                rec.reason(runlog.REASON_NULL_SCORES)
                rec.note(f"{null_scores} clusters stored with a null score")
        except Exception as exc:  # noqa: BLE001
            rec.status = "failed"
            rec.reason(runlog.REASON_WRITE_FAILED)
            rec.note(f"silver write failed: {type(exc).__name__}: {exc}")
            log.error(rec.notes[-1])
    return 1 if rec.status == "failed" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Norm's Newsletter silver stage")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="cluster and print, make no AI calls, write nothing",
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
