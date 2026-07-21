# SPEC.md - Norm's Newsletter

Status: v1.3 (aligned with DESIGN.md v1.0, locked for build)
Changes in v1.3: canonical_url normalization and run_id format (6.1);
configuration and secrets loading (6.10); ops.run_log table schema
(section 8).
Changes in v1.2: deployment identity decisions and the pre-launch
migration plan (section 13); resolved open questions.
Owner: Milind
Audience: written so a junior engineer can build from it.

Rule of ownership: SPEC.md owns data, schemas, prompts, and pipeline
behavior. DESIGN.md owns the visual system, components, page layouts, and
the voice standard. The edition.json schema in section 6.5 is canonical
for both documents.

---

## 1. What this project is

**Norm's Newsletter**: a fully automated daily news briefing. Norm is the
AI editor persona. Software collects news from many free sources all day,
AI groups and rates stories, and at 6am ET the system publishes:

1. A static webpage on GitHub Pages: headline, audio player, a numbered
   "Today at a glance" summary, and 15-20 stories that each expand into a
   full plain-English article (Background / What happened / Why it matters)
2. A ~10 minute two-host audio brief (MP3), also served as a podcast feed
3. A permanent, browsable archive of every past edition

Audience: general readers. Everything is written in plain English per the
voice standard in DESIGN.md section 8. No human touches the daily output.
Budget: under $25/month.

Mental model: a tiny automated newsroom.

| Newsroom role   | In this system                                    |
|-----------------|---------------------------------------------------|
| Reporters       | Source adapters (Python, no AI)                   |
| Copy desk       | Dedup + clustering (code) and scoring (small AI)  |
| Editor-in-chief | Editor agent (curation, one larger AI call)       |
| Staff writers   | Writer stage (one small AI call per story)        |
| Printing press  | Astro static build + TTS (code, no AI)            |
| Librarian       | Archival job (code, no AI)                        |

## 2. Rule zero

**AI makes judgments. Deterministic code does everything else.**

- AI is used only where there is no formula: scoring newsworthiness,
  curating the edition, writing story text and the audio script.
- Every AI output is structured JSON validated against a schema in code
  before use. AI never writes HTML, never touches storage directly, never
  deploys.
- On validation failure: retry once with the error included, then fall
  back to a deterministic path. Failures are contained at the smallest
  possible scope (a story, then the edition), never the whole pipeline.
- Style rule enforced in prompts and lint: never use em dashes in any
  generated text.

## 3. Glossary

- **Adapter**: a class that fetches from one source and normalizes output
  into the standard row format.
- **Idempotent**: safe to run twice; re-runs produce no duplicates.
- **Embedding**: a vector representing text meaning; similar texts have
  nearby vectors.
- **Cluster**: a group of items about the same real-world story.
- **Iceberg**: an open table format over files in object storage; gives
  safe appends, partitions, schema evolution, time travel.
- **Medallion**: bronze (raw) -> silver (enriched) -> gold (historical).
- **edition.json**: the contract between "AI decided" and "code renders".
- **Dead man's switch**: monitoring that alerts when a job does NOT run.

## 4. Architecture at a glance

```
ALL DAY (every 3 hours, mini PC):
  Sources -> Adapters -> bronze.raw_items -> silver jobs -> silver.story_clusters
                          (Iceberg on R2)    (dedup, cluster, score)

6:00 AM ET (GitHub Actions):
  silver.story_clusters
     -> Editor agent (curation) -> edition core        \
     -> Writer stage (per-story articles, parallel)     } edition.json
     -> Readability gate (code)                        /
     -> Audio build (script call + TTS -> MP3 to R2)
     -> Astro build (edition.json + committed archive) -> GitHub Pages
     -> ping healthchecks.io
     -> Archival job (bronze+silver -> gold, drop day partitions)
```

## 5. Repository layout

```
norms-newsletter/
  SPEC.md  DESIGN.md  CLAUDE.md
  config/
    sources.yaml         # adapter registry
    pipeline.yaml        # thresholds, budgets, schedules
  prompts/
    scoring_v1.md        # anchored rubric
    editor_v1.md         # curation + glance + summaries
    writer_v1.md         # per-story article (background/what/why + quote)
    audio_script_v1.md
    voice.md             # DESIGN.md section 8, verbatim, included by all
  src/
    adapters/            # one file per source
    config.py            # loads config/*.yaml + .env; only reader of env vars
    collector.py
    silver/  dedup.py  cluster.py  score.py
    editor/  run_editor.py  run_writers.py  schema.py  readability.py
    audio/   script.py  tts.py
    archive.py  runlog.py
  site/                  # Astro project (components per DESIGN.md 4)
    src/pages/  src/components/  src/styles/tokens.css
    content/editions/    # committed edition.json per day (publication record)
    fixtures/            # normal.json quiet.json fallback.json for dev
  .github/workflows/  publish.yml  collect_fallback.yml
  tests/
```

## 6. Component specifications

### 6.1 Source adapters

Interface:

```python
class Adapter(Protocol):
    name: str
    topic_hint: str
    def fetch(self, since: datetime) -> list[RawItem]: ...
```

RawItem / bronze schema:

| field         | type      | notes                                        |
|---------------|-----------|----------------------------------------------|
| item_id       | string    | sha256(canonical_url + published_at)[:32]    |
| source        | string    | adapter name                                 |
| source_type   | string    | rss / api / json                             |
| topic_hint    | string    |                                              |
| url           | string    |                                              |
| canonical_url | string    | tracking params stripped, redirects resolved |
| title         | string    |                                              |
| body_excerpt  | string    | first ~1200 chars                            |
| author        | string?   |                                              |
| published_at  | timestamp |                                              |
| fetched_at    | timestamp |                                              |
| run_id        | string    |                                              |
| ingest_date   | date      | partition column                             |

**run_id format.** UTC timestamp plus 4 random hex characters:
`YYYYMMDDTHHMMSSZ-xxxx`, for example `20260719T110003Z-a4f2`. One run_id
is generated per job run and written to every row that run produces,
including the ops.run_log row (section 8).

**canonical_url normalization.** `item_id` is
`sha256(canonical_url + published_at)[:32]`, so bronze dedup is only as
reliable as this function is deterministic. Two layers:

*Deterministic cleanup, always applied, no network:*
- lowercase the scheme and host
- strip `utm_*` parameters and known click IDs (`fbclid`, `gclid`,
  `msclkid`, `igshid`, `mc_cid`, `mc_eid`)
- drop the fragment
- remove a trailing slash from the path

*Redirect resolution, network, conditional:* applied only to URLs whose
host appears in `shortener_hosts` in config/pipeline.yaml. 3-second
timeout, maximum 5 hops. On any failure (timeout, error status, hop limit)
fall back to the cleaned raw URL. The resolved target is then run through
the deterministic cleanup.

The cleanup rules above are **frozen per spec version**. Changing them
changes every item_id and breaks dedup against existing bronze rows, so
they change only with a version bump and a documented migration. The
`shortener_hosts` list is different: it may change at any time, including
mid-day. The cost is that the same article fetched before and after the
change can produce two item_ids, which is an acceptable duplicate, not a
correctness failure.

Registry entry (config/sources.yaml):

```yaml
- name: hackernews
  adapter: adapters.hackernews.HackerNewsAdapter
  topic_hint: tech
  enabled: true
  max_items_per_run: 40
```

v1 sources (all free): Hacker News API; TechCrunch, Ars Technica RSS;
arXiv API (cs.AI, cs.LG); AI lab blogs (RSS); NewsAPI (existing key,
non-commercial tier); Finnhub news; FRED releases; Google News topic RSS
across multiple outlets and viewpoints; Federal Register API; SEC EDGAR
press RSS; OCC/Fed/FDIC press feeds; Nature news RSS; CISA advisories;
Krebs; The Hacker News. X/Twitter is OUT of v1 (decision log #1). GDELT
deferred to v1.1.

Rules: one adapter failing never fails the run (catch, log, continue);
respect max_items_per_run; every run writes per-adapter health metrics.

### 6.2 Collector runtime

Mini PC, systemd timer, every 3 hours 06:00-03:00 ET. Disabled GitHub
Actions workflow as backup launcher, same entry point. Fully idempotent.

### 6.3 Bronze: `bronze.raw_items`

Iceberg on Cloudflare R2 via R2 Data Catalog (Iceberg REST). PyIceberg
writes, no Spark. Partitioned by ingest_date. Append-only; duplicate
item_ids skipped. Read only by silver jobs and archival.

### 6.4 Silver processing

After each collection cycle:

a) **Dedup (code):** drop existing item_ids and same-day canonical_urls.

b) **Cluster (code):** local sentence-transformers embeddings (zero
cost); greedy clustering, join best cluster if cosine >= cluster_threshold
(config, start 0.82); identical canonical_url always merges.

c) **Score (AI, Haiku-class):** only new clusters and clusters whose
member count changed. System prompt prompts/scoring_v1.md: anchored rubric
with example stories for 3, 6, 9 per topic; prompt caching on. Strict JSON
out: `{score 1-10, topic, rationale (one sentence), confidence}`. Invalid
twice -> score=null, editor ignores.

`silver.story_clusters`: cluster_id, ingest_date (partition), topic,
headline, summary_seed, member_ids, member_count, sources, score,
rationale, model_version, prompt_version, scored_at. Every decision
logged; this table is the future eval dataset.

### 6.5 Edition generation (two AI stages + gate)

**Stage 1, Editor agent (Sonnet-class, one call).** Reads today's clusters
via DuckDB. Applies editorial policy (prompts/editor_v1.md, which includes
prompts/voice.md):
- Section skeleton: Tech, AI, Business, Finance, US Politics, World,
  Regulation, Science, Cyber (optional).
- Budget 15-20 stories, min 2 / max 4 per section, global ranking.
- Dead sections collapse into "briefly"; 3+ dead sections -> shrink the
  edition; broadly quiet day -> edition_type "quiet" with a 3-point glance.
- Outputs the edition core: metadata, key_points, per-story title +
  one-line summary + sources, briefly list.

**Stage 2, Writer stage (one small call per story, parallel).** Input: the
story's cluster excerpts plus relevant prior mentions retrieved from
gold.history. Output: the `article` block. Grounding rules:
- background is written only from the provided excerpts and prior-edition
  context; no specific facts (dates, numbers, names) not present in the
  grounding; general framing allowed.
- Quote policy: at most one quote per story; only a person speaking (an
  official, executive, researcher), never a passage of another outlet's
  prose; short (1-2 sentences); always attributed and linked. A length cap
  is lint-enforced.
- A story whose article fails validation twice publishes without an
  article block (no expand affordance). Story-sized failure, never
  edition-sized.

**Readability gate (code, editor/readability.py).** Flesch-Kincaid over
all generated text. Edition average must be grade <= 9. If over: one
automatic revision pass with failing sentences listed; if still over,
publish anyway and flag in the run log (availability beats perfection,
but the flag is reviewed).

**edition.json (canonical schema, JSON Schema in editor/schema.py):**

```json
{
  "date": "2026-07-19",
  "edition_number": 1,
  "edition_type": "normal | quiet | fallback",
  "headline_of_the_day": "string",
  "key_points": [ {"text": "string", "topic": "string"} ],
  "audio": {"url": "string", "duration_seconds": 564} ,
  "sections": [
    { "name": "Artificial intelligence",
      "stories": [
        { "cluster_id": "string",
          "slug": "string",
          "title": "string",
          "summary": "string, one sentence",
          "score": 9,
          "sources": [ {"name": "string", "url": "string"} ],
          "article": {
            "background": "string, one paragraph",
            "what_happened": "string, one paragraph",
            "why_it_matters": "string, one paragraph",
            "quote": {"text": "string", "attribution": "string",
                       "source_url": "string"}
          }
        } ] } ],
  "briefly": [ {"title": "string", "url": "string", "topic": "string"} ],
  "stats": {"items_ingested": 0, "clusters_considered": 0,
             "stories_run": 0, "sources": 0, "sections_held": 0}
}
```

Notes: `audio` nullable (TTS failure -> page without player). `article`
nullable per story. `quote` optional. key_points order = ranking; 4-6
points normal, 3 quiet; a quiet edition may include one point in Norm's
voice tagged topic "norm". Fallback editions carry only date,
edition_number, edition_type, and a ranked top-10 stories list (title,
score, primary source link).

### 6.6 Site build (no AI)

Astro renders edition.json against fixed templates (DESIGN.md 5). At
publish, the day's edition.json is committed to site/content/editions/;
the archive index, year and topic filter pages, permalinks, and prev/next
links are all built statically from those files. Stories render as native
details/summary (DESIGN.md StoryCard); the site works with JavaScript
disabled. Feeds: /feed.xml with podcast enclosures (DESIGN.md 7).
Analytics: GoatCounter.

URL configuration rule: the site's absolute URL and base path are defined
in exactly one place (astro.config: `site` and `base`) and everything that
needs an absolute URL (feed links, OG tags, audio enclosure URLs,
canonical links) derives from it. During the build phase this is
`site: "https://PERSONAL_USERNAME.github.io"`, `base:
"/norms-newsletter"`. The pre-launch migration (section 13) changes these
two values and nothing else in the codebase. No URL is ever hardcoded
anywhere.

### 6.7 Audio build

audio/script.py: one small model call turns edition.json into a two-host
dialogue (prompts/audio_script_v1.md + voice.md; hosts define terms to
each other; 1,300-1,600 words). audio/tts.py: multi-speaker TTS (Gemini
TTS behind a swappable interface). MP3 to R2 at /audio/YYYY-MM-DD.mp3;
the repo never stores audio. The audio job's ai_cost_estimate_usd
(section 8) is the sum of the script model call and the Gemini TTS render,
the render estimated from the TTS response's token usage and the per-token
prices in config/pipeline.yaml (audio.tts_price_input_per_mtok,
audio.tts_price_output_per_mtok).

### 6.8 Publish workflow (publish.yml)

1. Checkout, install. 2. Read silver via DuckDB. 3. Editor agent ->
validate. 4. Writer stage (parallel) -> validate per story. 5. Readability
gate. 6. Audio build -> upload. 7. Commit edition.json to
site/content/editions/. 8. Astro build -> deploy Pages. 9. Ping
healthchecks.io. 10. Archival job.

Scheduling: two crons `30 9 * * *` and `30 10 * * *` open a daily publish
window at 05:30 US Eastern (DST-correct: exactly one lands on 05:30 ET on
each side of the change). The gate proceeds when both hold: the current
Eastern wall-clock time is at or after 05:30 for today's date, AND today's
edition is not already committed to `site/content/editions/`. The
already-committed check (the publication record, decision #17), not an
exact-minute match, is what enforces one edition per day. This is
deliberate: GitHub fires scheduled crons late as a matter of course, and
never early, so an exact-minute gate silently skips the day whenever a
firing is delayed. Under the window plus idempotency rule, whichever firing
runs first after the window opens publishes, and the other firing, plus any
manual re-trigger, is a no-op because the day is already published. The
05:30 open (rather than 06:00) gives headroom for cron delay plus the
roughly 5 to 9 minute build so the site is live by 06:00 ET.
`workflow_dispatch` with `force: true` bypasses both conditions.

### 6.9 Archival job

After deploy: rewrite today's bronze and silver partitions into
gold.history (Iceberg, compacted Parquet, partitioned by month), store the
day's edition.json verbatim in gold, drop today's bronze/silver
partitions, expire snapshots older than 7 days. Gold is the permanent
record and the writer stage's background retrieval source.

### 6.10 Configuration and secrets

`src/config.py` is the single entry point for all configuration. It loads
`config/sources.yaml` and `config/pipeline.yaml`, plus `.env` locally
(Actions secrets in CI), and validates everything with pydantic models at
import time so a malformed registry or a missing credential fails loudly
at startup rather than mid-run.

**It is the only module in the codebase that reads environment
variables.** Every other module imports typed settings from it. A bare
`os.environ` or `os.getenv` outside `src/config.py` is a bug. No
credential is ever written to a file, logged, or committed.

`config/sources.yaml` holds the adapter registry (6.1). `config/pipeline.yaml`
holds operational values: `cluster_threshold`, per-run budgets, schedules,
and `shortener_hosts` (6.1). Keys are added by the milestone that needs
them, not speculatively.

## 7. Failure behavior

| Failure                        | Behavior                                        |
|--------------------------------|--------------------------------------------------|
| One adapter fails              | Log, skip, continue                              |
| Missed collector cycles        | Next cycle backfills via `since`; bronze dedups  |
| One story's article fails 2x   | Story publishes without article block            |
| Editor output invalid 2x       | Publish fallback edition (edition_type fallback) |
| Zero/near-zero data at 6am     | Publish quiet edition                            |
| Readability gate fails 2x      | Publish, flag in run log                         |
| TTS fails                      | Publish without audio row; log                   |
| Deploy fails                   | healthchecks.io alert (missing ping)             |

The fallback edition is a real page (DESIGN.md NoticeBanner + RankedList):
notice in Norm's voice, top 10 clusters by score, titles and links. The
site never silently skips a day and never shows a broken page.

## 8. Observability

**`ops.run_log` (Iceberg, partitioned by run_date).** One row per job run.
Written by every job, including failed ones; a job that cannot write its
own row is itself a failure surfaced by the dead man's switch.

| field              | type      | notes                                     |
|--------------------|-----------|-------------------------------------------|
| run_id             | string    | format per 6.1                            |
| job                | string    | collector / silver / editor / writer / audio / site / archive |
| started_at         | timestamp |                                           |
| ended_at           | timestamp |                                           |
| status             | string    | success / partial / failed                |
| items_in           | int       |                                           |
| items_out          | int       |                                           |
| adapter_metrics    | string?   | JSON blob: per-adapter items, errors, latency_ms; null for non-collector jobs |
| ai_cost_estimate_usd | double? | null for non-AI jobs; the sum of all AI calls in the job (audio: script + TTS render) |
| readability_flag   | boolean?  | editor job only, per 6.5                  |
| notes              | string?   | nullable                                  |
| run_date           | date      | partition column                          |

`status` is `partial` when the job completed but degraded: an adapter
failed and was skipped, a story published without an article block, or the
readability gate was exceeded and the edition published anyway. This is
the row that makes the weekly review possible.

healthchecks.io:
one check for 6am publish, one for the collector cadence. Weekly 10-minute
review: cluster quality, score distribution, readability flags; tune
cluster_threshold and rubric anchors.

## 9. Cost budget (monthly, target < $25)

| Line item                                   | Estimate |
|---------------------------------------------|----------|
| Scoring (Haiku-class, cached)               | $4-8     |
| Editor + writer stage (per-story articles)  | $6-10    |
| Audio script + TTS (~10 min/day)            | $3-6     |
| Embeddings (local)                          | $0       |
| R2 + catalog, Actions, Pages, monitoring    | ~$0      |
| Buffer                                      | $2-4     |

Levers if over: max_items_per_run, re-scoring rule, article length.

## 10. Decision log

| #  | Decision |
|----|----------|
| 1  | Multi-source, no X in v1 (cost + redistribution compliance) |
| 2  | Cluster threshold 0.82, config-driven, observed for 2 weeks |
| 3  | 15-20 stories, 2-4 per section, dead sections -> Briefly |
| 4  | Gemini multi-speaker TTS behind a swappable interface |
| 5  | Collectors on mini PC; disabled Actions cron as fallback |
| 6  | Incremental scoring; re-score only on cluster growth |
| 7  | Publish window opens 05:30 ET (dual cron, DST-correct) with an idempotency gate: publish only if today is not already committed. Idempotency, not an exact-minute match, prevents a second edition and survives GitHub's late or dropped crons; the earlier open leaves headroom to be live by 6am |
| 8  | Fallback edition; never skip a day silently |
| 9  | AI outputs are schema-validated JSON; code renders everything |
| 10 | Published site stores paraphrases + links, never source prose |
| 11 | Name: Norm's Newsletter; Norm is the editor persona |
| 12 | Stories are expandable: collapsed card + Background / What happened / Why it matters article, native details/summary |
| 13 | Two-stage generation: editor curates, writers draft per story in parallel; failures contained per story |
| 14 | Plain-English voice standard (DESIGN.md 8) + Flesch-Kincaid gate <= grade 9 in the publish workflow |
| 15 | Quote policy: person-speech only, one max, short, attributed, linked |
| 16 | Background grounding: cluster excerpts + gold retrieval only; no ungrounded specifics |
| 17 | Editions committed to the repo are the publication record; archive built statically from them |
| 18 | Ledger design system per DESIGN.md; light-only v1 |
| 19 | Build phase runs on Milind's personal GitHub account (project site at PERSONAL_USERNAME.github.io/norms-newsletter); a dedicated org and clean URL come via the pre-launch migration (section 13) |
| 20 | Public launch and podcast directory submission happen only AFTER the migration, so feed and episode URLs never change once subscribers exist |
| 21 | Contact email for the About page and feed metadata: aryanzodge1@gmail.com (interim; migration may move this to a project-owned address) |
| 22 | OBA/BD preclearance is a launch gate, not a build gate; repo stays private and the site unpublished until cleared |

## 11. Remaining open questions

- Whether briefly items get one-line summaries or titles only (v1: titles).
- Embedding model choice (candidate: bge-small or all-MiniLM).
- GDELT adapter in v1.1.
- Whether the migration (section 13) also moves API keys to a
  project-owned email/account set, and which providers allow it cleanly.

## 12. Build order

1. **M1 Skeleton:** repo, config loader, bronze schema, HN + one RSS
   adapter, PyIceberg to R2, run log.
2. **M2 Silver:** dedup, local embeddings, clustering, scoring rubric v1.
3. **M3 Edition:** editor + writer prompts, schema validation, readability
   gate, fixtures (normal/quiet/fallback), fallback path.
4. **M4 Site:** Astro implementation of DESIGN.md (tokens, components,
   three templates, pages, feed) developed against fixtures.
5. **M5 Automation:** publish.yml with DST logic, Pages deploy,
   healthchecks, archival job, gold table.
6. **M6 Audio + polish:** dialogue script, TTS, podcast feed, remaining
   adapters, OG images, two-week tuning period.

Definition of done for v1: 14 consecutive days of correct, unattended
publication.

## 13. Pre-launch migration plan (personal account -> project identity)

The project is built under Milind's personal GitHub account and personal
API accounts. Before public launch, it migrates to a self-contained
project identity. Because decision #20 delays podcast submission and
public launch until after this migration, no external URL ever breaks.

Target state:
- GitHub organization `norms-newsletter` containing repo
  `norms-newsletter.github.io`, serving the site at
  https://norms-newsletter.github.io (org root Pages site, base "/").
- Project email address (owns or receives for the accounts below and
  replaces the interim contact address if desired).
- API keys reissued under project-scoped tokens or accounts where the
  provider supports it (Anthropic, Cloudflare, Google, healthchecks.io,
  GoatCounter); keys that cannot move are rotated and documented.

Migration steps (target: after M6, before launch):
1. Create the org and the `norms-newsletter.github.io` repo; transfer the
   existing repo's history into it (git remote swap + push, or GitHub's
   repo transfer to the org followed by a rename).
2. Re-add all Actions secrets in the new repo (secrets do not transfer).
3. Change astro.config `site` to "https://norms-newsletter.github.io" and
   `base` to "/". Per the URL configuration rule (6.6) this is the only
   code change.
4. Update the mini PC collector's git remote.
5. Rotate any keys being moved to project ownership; verify spikes 5.1
   and 5.2 from SETUP.md still pass with the new credentials.
6. Run one full private publish cycle end to end on the new identity.
7. Flip the repo public, submit the podcast feed to directories, announce.

Exit criterion: one complete unattended 6am publish on the new URL with
healthchecks green.
