# CLAUDE.md - Norm's Newsletter

Orientation for every session. Read this first, then read the parts of
SPEC.md and DESIGN.md that cover the milestone you are working on.

## Source of truth

Two documents govern this repo. They are authoritative; this file only
distills them.

- **SPEC.md** owns data, schemas, prompts, and pipeline behavior.
- **DESIGN.md** owns the visual system, components, page layouts, and the
  voice standard.
- The `edition.json` schema in **SPEC.md section 6.5** is canonical for both
  documents. It is the **site's** record.
- The app's records are the story and newsletter schemas in **SPEC.md section
  14**. DESIGN.md does not yet cover the app's visual system, and the voice
  standard applies to both.

**If SPEC.md and DESIGN.md conflict, stop and ask Milind. Never resolve a
conflict yourself, and never pick the more convenient reading.**

**Two publishing paths now exist and neither is downstream of the other**
(SPEC decision #37). The site edition (6.5) is curated by the AI editor. The
app newsletter (14.4) is assembled per user by deterministic code. They share
collection, scoring, the writer stage, the readability gate, and the story
text. A change to one is not automatically a change to the other, and the
site keeps publishing while the app is built.

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
   (a story, then the edition or the newsletter), never the whole pipeline.
   Never an empty day for the site (decision #26), never an empty newsletter
   for a user (SPEC 14.4).
4. **Tests cover the deterministic layers**: adapters, dedup, clustering
   math, edition schema validation, the readability gate, the DST
   scheduling check, and the allocator (SPEC 14.4 names the assertions).
   Fixtures in `site/fixtures/` drive all front-end work. The site must
   never require the live pipeline to develop.
5. **Stack**: Python 3.12 with uv, PyIceberg for writes, DuckDB for
   reads, no Spark. Site is Astro with zero client JavaScript except the
   two scripts named in DESIGN.md section 7. User data lives in Postgres,
   never in the lake (decision #36): bronze, silver, and gold hold only news,
   so account deletion stays one `DELETE`. Credentials come from `.env`
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
  SPEC.md DESIGN.md      # authoritative, and the only two that are
  CLAUDE.md              # this file
  MILESTONES.md          # appended at the end of every milestone
  README.md              # what the project is, for someone arriving cold
  SETUP.md               # first-run bootstrap. SPEC 13 re-runs its Part 5 spikes
  RUNBOOK.md             # operating it: health checks, and what to do when it breaks
  APP-ARCHITECTURE.md    # + .png and -v2.drawio. A proposal. Governs nothing
  COST_ANALYSIS.md       # working note, open. Governs nothing
  STRESS_TEST_FINDINGS.md # working note, 2026-07-23. Governs nothing
  .claude/skills/milestone-verify/   # verification gate, run at milestone end
  config/
    sources.yaml         # adapter registry (SPEC 6.1)
    pipeline.yaml        # thresholds, budgets, schedules
  prompts/
    scoring_v1.md editor_v1.md writer_v1.md simplify_v1.md
    audio_script_v1.md
    voice.md             # DESIGN.md section 8 verbatim, included by all
  src/
    adapters/            # one file per source
    collector.py
    silver/   dedup.py cluster.py score.py
    editor/   run_editor.py run_writers.py schema.py readability.py
              simplify.py
    app/      allocator.py schema.py   # SPEC 14, per-user path (M7)
    audio/    script.py tts.py
    archive.py runlog.py
  site/                  # Astro (DESIGN.md section 4 component names)
    astro.config.mjs     # the ONLY place site + base are defined
    src/pages/ src/components/ src/styles/tokens.css
    content/editions/    # committed edition.json per day, the publication record
    fixtures/            # normal.json quiet.json fallback.json, drive front-end dev
  landing/               # the app's landing page (React/Vite), live at norm.news. No spec covers it
  prototypes/            # the Claude Design export of the app. Governs nothing
  spikes/                # credential and dependency smoke checks, not pipeline code
  scripts/               # operator tooling (norm.py), RUNBOOK.md points at it
  ops/trigger-worker/    # external publish trigger (SPEC 6.11), deploy infra
  .github/workflows/     # publish.yml collect.yml
  tests/
```

Directories not yet created are created by the milestone that needs them.
`spikes/` holds standalone checks (`check_iceberg.py`, `check_anthropic.py`,
`check_embeddings.py`, `check_tts.py`) and is not imported by `src/`. `scripts/`
is the other standalone directory and is not the same thing: spikes prove a
dependency or credential works once, scripts are the tools a caretaker runs to
operate the thing day to day. Neither is imported by `src/`.
`landing/` is a second front end and is not the site: it is React rather than
Astro, it publishes to `norm.news` rather than to Pages, and rule 1 has not
been satisfied for it. It being live is the reason to read
`landing/README.md` before touching it: the page makes claims the spec does
not carry, and the README lists them, along with what is ported from
`prototypes/` rather than designed.
It also **holds the only personal data in the project**: its waiting list is a
Cloudflare D1 table of email addresses, which is neither Postgres nor the lake
and so sits outside decision #36's enumeration. Deletion is still one
statement, which is what #36 actually guarantees, but the table has no spec
section and no retention period. `landing/PROPOSED-SPEC.md` is the addition it
owes and is the thing to read before extending it. **Nothing is broadcast to
that list until a real unsubscribe exists**: the signup confirmation is
transactional, a launch announcement is not.

## Data flow in one screen

Shared trunk, then two paths that never read each other.

```
SHARED (every 3h, GH Actions):
  sources -> adapters -> bronze.raw_items (Iceberg on R2)
          -> dedup -> cluster (local embeddings, cached by model_version)
          -> score (AI: topic_score, general_score, primary + secondary topics)
          -> silver.story_clusters

SITE PATH (6:00 am ET, Actions):
  silver -> editor agent (AI, curation) -> edition core
         -> writer stage (AI, per story, parallel) -> articles
         -> readability gate (code) -> simplify pass (AI, only if it fails)
         -> edition.json -> audio build -> Astro build -> Pages -> healthchecks
         -> archival job (bronze + silver -> gold.history)

APP PATH (SPEC 14, M7. per user, no editor):
  silver -> allocator (CODE, per user: topics, dedup, unseen, budget, top-up)
         -> intro (AI, one call, cached by story-ID-set hash)
         -> newsletter record (Postgres)
```

The only AI calls in the system: scoring, editor, writer, simplify, audio
script, and the per-user intro. Everything else is deterministic code. (TTS is
a model call too, but it renders audio rather than returning JSON, so it sits
outside the rule zero validate-and-retry path the others share.)

**The app path has exactly one AI call, and that is load-bearing.** Story text
is written once and reused by every user (SPEC 14.1), so cost tracks how much
news happened rather than how many people are reading. Any new AI call on the
per-user path breaks that, and is a design defect rather than a feature.

## Milestone workflow

**SPEC.md section 12 is authoritative for build order.** The table below is a
convenience index; if it disagrees with SPEC 12, SPEC 12 wins and this table
is the thing to fix.

| Milestone | Scope |
|-----------|-------|
| M1 Skeleton  | repo, config loader, bronze schema, HN + one RSS adapter, PyIceberg to R2, run log |
| M2 Silver    | dedup, local embeddings, clustering, scoring rubric v1 |
| M3 Edition   | editor + writer prompts, schema validation, readability gate, fixtures, fallback path |
| M4 Site      | Astro build of DESIGN.md against fixtures |
| M5 Automation| publish.yml with DST logic, Pages deploy, healthchecks, archival, gold |
| M5.1 Trigger | external publish trigger (SPEC 6.11) + timeliness measure; lands before the 14-day run starts |
| M6 Audio     | dialogue script, TTS, podcast feed, remaining adapters, OG images, tuning. **Audio format superseded by decision #44**; rework lands in M8 |
| M7 App data  | SPEC 14 schemas + allocator + entitlements (14.10, needed by allocator rule 1). Two-score scoring lands first and additively, so the site keeps publishing |
| M8 Delivery  | read-time scheduling and assembly loop (14.6), app API with versioning and account deletion (14.7), audio rework to single voice + per-story clips (6.7, decision #44) |
| M9 Mobile    | Expo client and EAS release pipeline (14.9) |
| M10 Agent    | chat and story tracker on Managed Agents (14.8), Story MCP server, server-side feature flag |

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

14 consecutive days of correct, unattended publication. *Correct* includes on
time: a publication that is late under the SPEC section 8 timeliness measure
breaks the streak, the same as a missed or degraded day.

This is a property of the **site**, and M7 does not gate it. App work must not
be allowed to break a streak the site is otherwise achieving.

## Four rules that are easy to break by accident

These are specified in SPEC section 14 and are each one line to violate.

1. **No AI call on the per-user path except the intro.** Story text is written
   once and reused (14.1). A second per-user call makes cost scale with users.
2. **The client never supplies a prompt, a `user_id`, or its own plan.** All
   three come from the authenticated identity, server-side (14.7, 14.8,
   14.10). A client-asserted plan is a paywall bypass.
3. **Never store a precomputed UTC read time.** Resolve it from
   `read_time_local` plus IANA `timezone` on every pass (14.6, decision #38).
4. **Agent output is displayed and discarded.** It never enters a story
   record, a newsletter record, or any table (14.8, decision #41).

## Not yet specified

Do not build these. Rule 1 applies: propose a spec addition and wait.

- The app's visual system. DESIGN.md covers the site only; the voice standard
  applies to both.
- Source health checks and automatic quarantine.
- Anything in section 11's open questions. After decisions #48 to #51 the
  app-layer remainder is data retention, the allocator top-up rules, the
  free-tier allowance, and push notification copy.
- Free-text topics and the Sunday retrospective. Both appear in the app
  prototype as paid features and both are explicitly deferred by 14.10.

`APP-ARCHITECTURE.md` and `APP-ARCHITECTURE-v2.drawio` describe the intended
end state in plain English. **They are proposals and govern nothing.** Where
they disagree with SPEC.md, SPEC.md wins.
