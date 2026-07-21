# `src/` - the Python pipeline

This is the whole backend: everything that collects news, groups and rates it,
generates the daily edition, builds the audio, and archives the record. The
Astro website lives separately in [`../site/`](../site/).

If you read one thing first, read the top-level [`../README.md`](../README.md)
for the end-to-end pipeline, then [`../CLAUDE.md`](../CLAUDE.md) for the rules.

## The golden rule ("rule zero")

**AI makes judgments. Deterministic code does everything else.** An AI is called
in exactly four places (scoring, editor, writers, audio script). Every AI output
is JSON validated against a schema *in code* before use. On failure: retry once
with the error, then fall back deterministically, containing the failure to the
smallest scope. Nothing else in here calls a model.

A related rule you will see enforced: **`config.py` is the only module allowed to
read environment variables or secrets.** Every other module imports typed
settings from it. A bare `os.environ` anywhere else is a bug.

## How the files fit together

### Entry points (things you run with `python -m src....`)

| Module | What it runs | When |
|--------|--------------|------|
| `collector.py` | One collection cycle: fetch every source, enrich, write to bronze | Every 3 hours |
| `silver/run_silver.py` | Dedup, cluster, and score the day's bronze | After each collect |
| `editor/run_edition.py` | Build the day's `edition.json` (editor + writers + readability) | 6am daily |
| `audio/run_audio.py` | Write the audio script, render the MP3, upload it | 6am daily |
| `archive.py` | Fold the day into the permanent `gold` tables | 6am daily, last |

Each entry point supports `--dry-run` (no AI calls, nothing written) and
`--date YYYY-MM-DD` (re-run a past day). Each is fully **idempotent**: running it
twice over the same data does not create duplicates or double-charge for AI.

### Shared building blocks (imported by the entry points)

| Module | Responsibility |
|--------|----------------|
| `config.py` | Loads and validates `config/*.yaml` and `.env`. The single source of settings and secrets. |
| `storage.py` | The one place that knows how to reach the R2 Iceberg catalog and the R2 audio bucket. |
| `bronze.py` | The `bronze.raw_items` table: schema, append (skipping duplicates), and per-day reads. |
| `enrich.py` | Fetches each item's real article page so `body_excerpt` is substantial. Never fatal. |
| `runlog.py` | The `ops.run_log` table: one row per job run, plus the `run_id` generator. |
| `health.py` | healthchecks.io "dead man's switch" pings. Never raises; a missed ping is the alert. |
| `schedule.py` | The DST-correct "is it 6am US Eastern?" check used by the publish workflow. |
| `archive.py` | The `gold.*` permanent tables and the daily archival job. Also feeds "prior coverage." |

### Subpackages

| Folder | What it does | README |
|--------|--------------|--------|
| `adapters/` | One file per news source, all producing the same normalized row | [`adapters/README.md`](adapters/README.md) |
| `silver/` | Dedup, local-embedding clustering, and AI scoring | [`silver/README.md`](silver/README.md) |
| `editor/` | The whole edition: curation, article writing, readability, schema | [`editor/README.md`](editor/README.md) |
| `audio/` | The two-host dialogue script and text-to-speech | [`audio/README.md`](audio/README.md) |

## Data flow through these modules

```
adapters/*  ->  enrich.py  ->  bronze.py (bronze.raw_items)
                                   |
                                   v
              silver/dedup -> silver/cluster -> silver/score  ->  silver/table (silver.story_clusters)
                                   |
                                   v
              editor/context -> editor/plan -> editor/run_editor (AI)
                                             -> editor/run_writers (AI)
                                             -> editor/readability + editor/simplify
                                             -> editor/assemble -> editor/schema (validate)
                                             -> site/content/editions/<date>.json
                                   |
                                   v
              audio/script (AI) -> audio/tts -> storage (R2 MP3) -> inject into edition.json
                                   |
                                   v
              archive.py: bronze + silver + edition.json  ->  gold.*  ->  drop daily partitions

(every job also writes one row via runlog.py, and pings health.py)
```

## Conventions you will see everywhere

- **Validator before prompt.** For any AI stage, the pydantic schema that
  defines a valid response is written first and is the authority. The prompt is
  asked to match a schema *derived from* that model.
- **Contain failures.** Broad `except` blocks that log and continue are
  deliberate here, not sloppy: one bad source, one bad story, or one bad cluster
  must never take down a run. The `# noqa: BLE001` comments mark these on
  purpose.
- **Every module cites its SPEC section** in its docstring (for example
  "SPEC 6.4c"). When in doubt about *why* code does something, that section in
  [`../SPEC.md`](../SPEC.md) explains it.
- **Frozen vs. tunable.** Some rules are "frozen per spec version" (like URL
  cleanup, which feeds the dedup hash) and must not change without a migration.
  Others (thresholds, model ids, source list) live in `config/` and can change
  freely.

## Testing

The deterministic layers are covered by the pytest suite in
[`../tests/`](../tests/), which runs **fully offline**: network adapters use a
mock transport and Iceberg writes go to a local SQLite catalog. AI calls are not
tested (they are judgment), but their schema validators and retry paths are.
