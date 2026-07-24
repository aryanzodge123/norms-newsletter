# COST_ANALYSIS.md - LLM cost, open investigation

Status: **open, do not act yet.** This is a working note, not spec. It records a
cost finding from a single edition and lays out where the money goes and how we
might reduce it. Nothing here is decided. Any change it points to is
SPEC-governed (models are pinned in SPEC 6.5, budgets live in
`config/pipeline.yaml`) and needs the usual spec-first, one-milestone process.

## TL;DR

**Corrected 2026-07-23.** The headline figure below was wrong by about 4x, and
the ranked drivers were wrong too. Both errors have the same cause.

Per-edition Anthropic spend is **~$0.85**, not $3.42. At 30 editions/month that
is **~$25/month**, which lands on the SPEC 9 target rather than 4x over it.

**Why the old number was wrong.** It came from 2026-07-20, which has **14
editor runs and 16 audio runs** in `ops.run_log`. That was a development day of
re-runs, not one edition. Summing a day's rows silently summed the re-runs. Per
*run* that day the editor was ~$0.195, which matches the clean days exactly.

Two reasons still not to over-tune:

1. **Small n.** Two clean production days. Gather ~14 before trusting an
   average, and count the editor runs per day when you do.
2. **The editor row still bundles three sub-stages**, so it is not fully
   attributable. Instrumentation before tuning still holds.

## The measurement

Query: `scratchpad/runlog_costs.py` (reads `ops.run_log.ai_cost_estimate_usd`
via the R2 Data Catalog; needs `R2_CATALOG_URI` / `R2_WAREHOUSE` / `R2_TOKEN`).
**Group by run_date *and* count rows per job**: a day with more than one editor
row is not an edition.

Per-day Anthropic cost, all four days on record:

| run_date   | editor runs | silver  | editor  | audio   | total   |
|------------|-------------|---------|---------|---------|---------|
| 2026-07-20 | **14**      | $0.3429 | $2.7245 | $0.3558 | $3.4232 |
| 2026-07-21 | 2           | $0.1816 | $0.1865 | $0.1756 | $0.5437 |
| 2026-07-22 | **1**       | $0.3723 | $0.2927 | $0.1524 | **$0.8174** |
| 2026-07-23 | **1**       | $0.3977 | $0.3150 | $0.1595 | **$0.8722** |

Only the last two are single-edition days. 07-20 is the contaminated one the
old TL;DR was built on; 07-21 was a thin day (32 items, 7 sources).

Per clean edition, roughly:

| stage                                  | cost          | share |
|----------------------------------------|---------------|-------|
| silver (scoring, one Haiku call/cluster) | $0.37-0.40  | ~45%  |
| editor (curation + writers + readability) | $0.29-0.32 | ~36%  |
| audio (script + Gemini TTS)             | $0.15-0.16   | ~19%  |
| collector, site, archive                | $0.00         | no AI |

Caveats that still apply:

- **`writer` = $0.00 is a reporting artifact.** Edition generation runs under a
  single `JOB = "editor"` row (`src/editor/run_edition.py:35`), so curation,
  writers, and readability all land in the editor figure.
- **Audio now includes the render.** The 07-23 row reads
  `audio 456s, 5475168 bytes (script $0.0445 + tts $0.1150)`. The change that
  folds Gemini TTS into `ai_cost_estimate_usd` has landed; it does not backfill
  past rows, so 07-20's audio figure is script-only.

## Measured directly, not from run_log

The editor **curation call alone** was measured against the real 2026-07-23
edition by rebuilding its user message from gold and counting tokens with
`messages.count_tokens`:

- 161 scored candidates, 29,706 input tokens of user message
- 1,851 tokens of system prompt, ~1,251 tokens of JSON out
- **$0.115** at Sonnet 4.5 rates

So curation is about a tenth of the old $2.72 story, and writers plus
readability account for roughly $0.20 of a clean editor row.

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

## Cost drivers, ranked (revised 2026-07-23)

The old ranking put the readability loop first. That was an artifact of the
bundled re-runs: on clean days silver outspends the entire editor row.

1. **Scoring volume.** The largest single line, $0.37-0.40, ahead of everything
   else. Cheap per call, but one Haiku call per cluster across 8 collections a
   day, and it scales with how many clusters form: 161 clusters on 07-23 against
   32 on the thin 07-21. This is where the money actually is.
2. **Editor Sonnet context.** $0.115 of the editor row, measured. A single
   Sonnet call carrying every scored cluster in an un-cached user message, so
   its input size matters more than any Haiku stage. Note it scales with cluster
   count too, which means adding sources raises both this and scoring.
3. **The readability loop.** Real but smaller than assumed: writers plus
   readability come to roughly $0.20 of a clean editor row. Still the largest
   call-count multiplier and still the least visible, so still worth
   instrumenting, just not the prime suspect.
4. **Audio.** $0.15-0.16, of which the TTS render is $0.115 and the script call
   $0.045.

The common thread in 1 and 2 is cluster count. Both grow as sources are added,
which makes cluster volume the lever with the widest effect.

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

## Non-AI costs

Effectively free, with one line worth watching:

- **GitHub Actions.** About 35.5 min/day of job wall time across all jobs,
  measured from `ops.run_log` start/end timestamps on 07-22 and 07-23, so
  ~1,065 min/month before workflow overhead (checkout, `uv` install, the Astro
  build). The private-repo free tier is 2,000 min/month on Free and 3,000 on
  Pro. Inside it, but not by a wide margin, and this is the line that grows as
  sources are added. Overage is $0.008/min on Linux.
- **R2.** Audio is ~5.5MB/day and the Iceberg tables are small. Well inside the
  10GB / 1M Class A / 10M Class B free tier, and egress is free.
- **Pages, healthchecks.io.** Free tiers.

## Next steps

1. Let ~14 clean editions accrue, then re-run `scratchpad/runlog_costs.py`,
   **counting editor runs per day** so a re-run day cannot contaminate the
   average the way 2026-07-20 did.
2. Land per-sub-stage cost instrumentation so the editor row is decomposable
   (curation is now measured directly, writers and readability are not).
3. Only then evaluate the levers above, spec-first, one at a time, against the
   readability and voice quality bars in DESIGN.md / SPEC 6.5. Given the revised
   ranking, cluster volume is the first place to look, not the readability loop.
4. Watch the Actions minutes as sources are added.
