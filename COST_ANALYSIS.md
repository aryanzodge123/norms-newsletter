# COST_ANALYSIS.md - LLM cost, open investigation

Status: **open, do not act yet.** This is a working note, not spec. It records a
cost finding from a single edition and lays out where the money goes and how we
might reduce it. Nothing here is decided. Any change it points to is
SPEC-governed (models are pinned in SPEC 6.5, budgets live in
`config/pipeline.yaml`) and needs the usual spec-first, one-milestone process.

## TL;DR

The first real per-edition cost, pulled from `ops.run_log`, is **~$3.42 in
Anthropic spend**, roughly 3-4x an earlier back-of-envelope guess. Almost all of
it is the `editor` job at **$2.72**. Projected naively at 30 editions/month that
is **~$100/month** of Claude spend, plus Gemini TTS on top.

Two reasons not to act on this yet:

1. **n = 1.** This is one edition (2026-07-20). The monthly figure is `avg x 30`
   off a single data point. Gather ~14 editions before trusting an average.
2. **The $2.72 is not yet attributable.** The `editor` run_log row bundles three
   sub-stages (see below), so we cannot see which one dominates. The first real
   work here is instrumentation, not tuning.

## The measurement

Query: `scratchpad/runlog_costs.py` (reads `ops.run_log.ai_cost_estimate_usd`
via the R2 Data Catalog; needs `R2_CATALOG_URI` / `R2_WAREHOUSE` / `R2_TOKEN`).

Per-edition Anthropic cost, 2026-07-20:

| job (run_log)        | cost    | what it actually covers                         |
|----------------------|---------|-------------------------------------------------|
| silver (scoring)     | $0.3429 | Haiku scoring, one call per cluster             |
| editor               | $2.7245 | editor curation + writer stage + readability loop |
| writer               | $0.0000 | not real: writer spend is inside the editor row |
| audio (script)       | $0.3558 | Haiku dialogue script only (no TTS, see below)  |
| **total / edition**  | **$3.4232** |                                             |

Caveats baked into these numbers:

- **`writer` = $0.00 is a reporting artifact.** Edition generation runs under a
  single `JOB = "editor"` row (`src/editor/run_edition.py:35`), so curation,
  writers, and readability all land in the editor figure.
- **Audio is script-only.** The historical row predates the change that folds
  Gemini TTS into the audio cost. Going forward the audio figure will include
  the render; it is still uncommitted at the time of writing.
- **n = 1**, as above.

## The AI call sites

Per CLAUDE.md the only AI calls are scoring, editor, writer, and audio script.
The readability gate adds a fifth path: it re-invokes the writer plus a simplify
call, up to `readability_max_passes` times.

All four text stages share one call helper, `call_validated` in
`src/editor/llm.py` (scoring and audio mirror the same shape). It applies
`cache_control: ephemeral` to the **system prompt only** (`src/editor/llm.py:151`;
also `src/silver/score.py:218`, `src/audio/script.py:89`). The per-call content
lives in the **user message and is billed at full input price every call.**
Pricing table: `src/editor/llm.py:27`. Cost from usage: `estimate_cost_usd`
(`src/editor/llm.py:63`).

| stage | model (price $/M in,out) | call pattern | input driver | output cap | caching |
|-------|--------------------------|--------------|--------------|-----------|---------|
| Scoring | Haiku 4.5 (1 / 5) | 1 per cluster, every 3h on the mini PC | rubric + cluster title/excerpt | 512 | rubric cached (read 0.1x after 1st) |
| Editor curation | **Sonnet 4.5 (3 / 15)** | 1 per edition | all scored clusters + excerpts (user msg) | 4096 | system cached, but 1 call so **written, never read** = no gain |
| Writers | Haiku 4.5 (1 / 5) | 1 per story, `writer_concurrency: 6` | per-story grounding text (user msg) | 2048 | system cached across stories; grounding un-cached |
| Readability | Haiku 4.5 (1 / 5) | up to 3 passes/edition | whole-edition simplify + re-write per failing story | simplify 4096 / rewrite 2048 | system cached; edition + grounding un-cached |
| Audio script | Haiku 4.5 (1 / 5) | 1 per edition | edition.json content | 8192 | system cached (1 call) |

Model ids and budgets: `config/pipeline.yaml` (`scoring_model`, `editor_model`,
`writer_model`, `script_model`, `writer_concurrency: 6`,
`readability_max_passes: 3`, `min_clusters_for_normal: 12`).

## Cost drivers, ranked (hypotheses, pending attribution)

1. **The readability loop.** Up to 3 passes, each a whole-edition Haiku simplify
   call plus a re-write of every failing story (`src/editor/run_edition.py:66`).
   This is the largest call-count multiplier and the least visible, because it is
   buried in the editor row. Prime suspect for the size of the $2.72.
2. **Editor Sonnet context.** A single Sonnet call carrying every scored cluster
   with excerpts in the un-cached user message. Sonnet at $3/$15 makes its input
   size matter more than any Haiku stage.
3. **Scoring volume.** Cheap per call, but one Haiku call per cluster across 8
   collections/day; total scales with how many clusters form.

## Candidate levers

Each needs measurement first and a SPEC decision. None are recommended yet.

- **Attribute the editor row (do this first).** Add a per-sub-stage cost
  breakdown (curation vs writers vs each readability pass) to the editor log /
  run_log notes. We cannot tune a $2.72 aggregate we cannot decompose. Highest
  priority; unblocks every lever below.
- **Cache the writer user-message prefix.** Today only the system prompt is
  cached. The writer stage repeats a stable prefix (guide, prior-mentions block)
  across ~12+ per-story calls; moving that behind a cache breakpoint would cut
  repeated input. `src/editor/context.py` builds the writer context.
- **Trim the readability loop.** Lower `readability_max_passes`, revise only the
  stories over the limit (confirm current behavior), or use a cheaper simplify.
  Measure per-pass cost before touching the quality gate.
- **Trim editor context.** Fewer clusters or shorter excerpts sent to the Sonnet
  curation call.
- **Model choice.** Editor is Sonnet 4.5. Sonnet 5 is more capable at lower intro
  pricing ($2/$10 vs $3/$15). Models are pinned for eval stability (SPEC 6.5), so
  this is an eval-gated spec change, not a config tweak.
- **Batch API (50% off).** Scoring runs on the mini PC every 3h and is not
  latency-critical, so it could batch cleanly. Editor/writer sit in the 6am
  publish window; batching them risks the publish deadline. Weigh per stage.
- **Pre-filter clusters before scoring.** Drop obviously low-signal clusters with
  deterministic heuristics before paying for a Haiku scoring call.

## Next steps

1. Let ~14 editions accrue, then re-run `scratchpad/runlog_costs.py` for a real
   average and a meaningful "last 14 avg" instead of an n=1 projection.
2. Land per-sub-stage cost instrumentation so the editor row is decomposable.
3. Only then evaluate the levers above, spec-first, one at a time, against the
   readability and voice quality bars in DESIGN.md / SPEC 6.5.

The pending audio change (Gemini TTS folded into `ai_cost_estimate_usd`) makes
the audio figure complete from here on; it does not backfill past rows.
