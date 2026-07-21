# CLAUDE.md - Norm's Newsletter

Orientation for every session. Read this first, then read the parts of
SPEC.md and DESIGN.md that cover the milestone you are working on.

## Source of truth

Two documents govern this repo. They are authoritative; this file only
distills them.

- **SPEC.md** owns data, schemas, prompts, and pipeline behavior.
- **DESIGN.md** owns the visual system, components, page layouts, and the
  voice standard.
- The `edition.json` schema in **SPEC.md section 6.5** is canonical for
  both documents.

**If SPEC.md and DESIGN.md conflict, stop and ask Milind. Never resolve a
conflict yourself, and never pick the more convenient reading.**

## The seven working rules

1. **No Spec, No Code.** If a behavior is not covered by SPEC.md or
   DESIGN.md, write a proposed spec addition and wait for approval before
   implementing it. Do not infer requirements from what seems reasonable.
2. **One milestone at a time**, in the exact order of SPEC.md section 12.
   Start each milestone with a short plan. End it by showing how to
   verify it works, and by appending to MILESTONES.md.
3. **Rule zero (SPEC section 2).** AI calls output schema-validated JSON
   only. Deterministic code does everything else: no AI writes HTML,
   touches storage, or deploys. **Write the validator before the prompt.**
   On validation failure, retry once with the error included, then fall
   back to a deterministic path. Contain failures at the smallest scope
   (a story, then the edition), never the whole pipeline.
4. **Tests cover the deterministic layers**: adapters, dedup, clustering
   math, edition schema validation, the readability gate, and the DST
   scheduling check. Fixtures in `site/fixtures/` drive all front-end
   work. The site must never require the live pipeline to develop.
5. **Stack**: Python 3.12 with uv, PyIceberg for writes, DuckDB for
   reads, no Spark. Site is Astro with zero client JavaScript except the
   two scripts named in DESIGN.md section 7. Credentials come from `.env`
   locally and Actions secrets in CI. **Never write a key into a file.**
6. **URLs derive from `astro.config` only.** Build phase values:
   `site: "https://aryanzodge123.github.io"`,
   `base: "/norms-newsletter"`. Feed links, OG tags, audio enclosure
   URLs, and canonical links all derive from these. A hardcoded URL
   anywhere is a bug. The pre-launch migration (SPEC section 13) changes
   these two values and nothing else.
7. **Never use an em dash** in any generated text, prompt file, code
   comment, or user-facing copy. Use periods, commas, or restructure.
   This applies to text you write as well as text the pipeline writes.

## Repo map

```
norms-newsletter/
  SPEC.md DESIGN.md CLAUDE.md MILESTONES.md
  .claude/skills/milestone-verify/   # verification gate, run at milestone end
  config/
    sources.yaml         # adapter registry (SPEC 6.1)
    pipeline.yaml        # thresholds, budgets, schedules
  prompts/
    scoring_v1.md editor_v1.md writer_v1.md audio_script_v1.md
    voice.md             # DESIGN.md section 8 verbatim, included by all
  src/
    adapters/            # one file per source
    collector.py
    silver/   dedup.py cluster.py score.py
    editor/   run_editor.py run_writers.py schema.py readability.py
    audio/    script.py tts.py
    archive.py runlog.py
  site/                  # Astro (DESIGN.md section 4 component names)
    astro.config.mjs     # the ONLY place site + base are defined
    src/pages/ src/components/ src/styles/tokens.css
    content/editions/    # committed edition.json per day, the publication record
    fixtures/            # normal.json quiet.json fallback.json, drive front-end dev
  spikes/                # credential and dependency smoke checks, not pipeline code
  .github/workflows/     # publish.yml collect.yml
  tests/
```

Directories not yet created are created by the milestone that needs them.
`spikes/` holds standalone checks (`check_iceberg.py`, `check_anthropic.py`,
`check_embeddings.py`, `check_tts.py`) and is not imported by `src/`.

## Data flow in one screen

```
every 3h (GH Actions): sources -> adapters -> bronze.raw_items (Iceberg on R2)
                     -> dedup -> cluster (local embeddings) -> score (AI)
                     -> silver.story_clusters

6:00 am ET (Actions): silver -> editor agent (AI, curation) -> edition core
                      -> writer stage (AI, per story, parallel) -> articles
                      -> readability gate (code) -> edition.json
                      -> audio build -> Astro build -> Pages -> healthchecks
                      -> archival job (bronze + silver -> gold.history)
```

The only AI calls in the system: scoring, editor, writer, audio script.
Everything else is deterministic code.

## Milestone workflow

Build order lives in SPEC.md section 12. Work one milestone at a time:

| Milestone | Scope |
|-----------|-------|
| M1 Skeleton  | repo, config loader, bronze schema, HN + one RSS adapter, PyIceberg to R2, run log |
| M2 Silver    | dedup, local embeddings, clustering, scoring rubric v1 |
| M3 Edition   | editor + writer prompts, schema validation, readability gate, fixtures, fallback path |
| M4 Site      | Astro build of DESIGN.md against fixtures |
| M5 Automation| publish.yml with DST logic, Pages deploy, healthchecks, archival, gold |
| M6 Audio     | dialogue script, TTS, podcast feed, remaining adapters, OG images, tuning |

For each milestone:

1. **Plan.** Post a short plan naming what gets built, which spec sections
   cover it, and what the tests will assert. Wait for approval.
2. **Build.** Validators before prompts. Tests alongside the deterministic
   code, not after.
3. **Verify.** Run the `milestone-verify` skill. Then show Milind the
   concrete commands to confirm the milestone himself.
4. **Log.** Append a MILESTONES.md entry: what was built, which spec
   sections it satisfies, how it was verified, and anything deferred.

Do not start the next milestone until the current one is logged and
approved.

## Definition of done for v1

14 consecutive days of correct, unattended publication.
