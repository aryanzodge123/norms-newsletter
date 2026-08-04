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
2. A ~10 minute single-voice audio brief (MP3), also served as a podcast feed
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
ALL DAY (every 3 hours, GitHub Actions):
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
  ops/
    trigger-worker/      # external publish trigger (6.11): deployment
                         # infrastructure, not pipeline code, never
                         # imported by src/
  .github/workflows/  publish.yml  collect.yml
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

**Transient fetch retries.** A source adapter may retry a transient fetch
failure (a timeout, HTTP 429, or a 5xx) a small bounded number of times with
backoff before giving up. A give-up is still the "one adapter fails, log and
skip" path (section 7): the cycle is `partial`, never `failed`, on that
adapter alone. This is a per-adapter resilience measure, applied where a
source is observed to be flaky (arXiv's query API times out often), not a
guarantee every adapter makes.

Registry entry (config/sources.yaml):

```yaml
- name: hackernews
  adapter: adapters.hackernews.HackerNewsAdapter
  topic_hint: tech
  enabled: true
  max_items_per_run: 40
```

**topic_hint vocabulary.** One of the ten section-skeleton values (6.5),
lowercased: tech, ai, business, finance, politics, world, regulation,
science, cyber, sports. (politics is the hint form of the "US Politics"
section.)
The hint is advisory provenance only. It is written to the bronze record
but nothing in silver or scoring reads it; the scoring stage (6.4c) assigns
each story its real topic from the article text. So a general or mixed feed
carries the hint that best describes its dominant beat, and the scorer still
routes individual stories to their correct section.

v1 sources (all free): Hacker News API; TechCrunch, Ars Technica RSS;
arXiv API (cs.AI, cs.LG); AI lab blogs (RSS); NewsAPI (existing key,
non-commercial tier); Finnhub news; FRED releases; Google News topic RSS
across multiple outlets and viewpoints; Federal Register API; SEC EDGAR
press RSS; OCC/Fed/FDIC press feeds; Nature news RSS; CISA advisories;
Krebs; The Hacker News; NPR and PBS NewsHour RSS (neutral public
broadcasters, World and US Politics beats, via the generic RSSAdapter).
The US Politics section, unstaffed by any dedicated source before, gets its
first feeds here (npr_politics, pbs_politics), the same way the World beat
was staffed with direct publisher feeds. The Science section, carried by
Nature alone (arXiv is topic_hint ai), is expanded with Quanta Magazine,
Science News, and NASA (quanta_magazine, science_news, nasa_news), curated
general-audience science journalism plus a public-domain agency feed, all
free keyless RSS via the generic RSSAdapter. The Business and Economics
beat, carried by two market-news desks (bbc_business, cnbc_business), is
expanded with three primary sources (bea_news, eia_today, ecb_press: the
US statistical agency, the US energy agency, and the non-US central bank
counterpart to federal_reserve_press) and three neutral-rated journalism
feeds (npr_economy, pbs_economy, the_conversation_business), again all free
keyless RSS via the generic RSSAdapter. X/Twitter is OUT of v1 (decision
log #1). GDELT deferred to v1.1.

Rules: one adapter failing never fails the run (catch, log, continue);
respect max_items_per_run; every run writes per-adapter health metrics.

### 6.2 Collector runtime

GitHub Actions (`collect.yml`), cron `0 */3 * * *`, every 3 hours. Runs
`src.collector` then `src.silver.run_silver`, writing bronze and silver to
R2 and pinging the collector-cadence check. Fully idempotent (bronze
dedups), so overlapping runs are harmless. A local machine may run the same
entry point as an optional supplement, but the pipeline no longer depends on
it. (The 2026-07-20 gap was a local MacBook Air that slept while no cloud
collector was enabled.)

### 6.3 Bronze: `bronze.raw_items`

Iceberg on Cloudflare R2 via R2 Data Catalog (Iceberg REST). PyIceberg
writes, no Spark. Partitioned by ingest_date. Append-only; duplicate
item_ids skipped. Read only by silver jobs and archival.

### 6.4 Silver processing

After each collection cycle:

a) **Dedup (code):** drop existing item_ids and same-day canonical_urls.

b) **Cluster (code):** local sentence-transformers embeddings (zero
cost), model `BAAI/bge-small-en-v1.5` (settled before the M2 build, over
all-MiniLM, which was the other candidate); greedy clustering, join best
cluster if cosine >= cluster_threshold (config, start 0.82); identical
canonical_url always merges. cluster_threshold is calibrated against this
specific model, so changing the model is a re-tuning event and not a config
tweak. Embeddings are never a stored source of truth: clustering, the
headline gate, and gold retrieval can each recompute them per run, so a model
change costs a threshold re-calibration but no data migration.

They may be **cached**, keyed by `(item_id, model_version)`. A cache is not a
schema: a miss recomputes exactly as before, so nothing downstream may treat a
stored vector as required input. A model change invalidates the cache by
version rather than migrating it, which is what preserves the property above.
`model_version` is stored alongside every vector so a stale entry can never be
served against a newer model.

The cache exists because the app layer (section 14) matches stories against
topics continuously rather than once per edition, which makes recomputation
the dominant cost of a per-user query rather than a negligible one. Storing
nothing was right when embeddings were used twice a day (decision #35).

c) **Score (AI, Haiku-class):** only new clusters and clusters whose
member count changed. System prompt prompts/scoring_v1.md: anchored rubric
with example stories for 3, 6, 9 per topic; prompt caching on. Strict JSON
out:

```
{ topic_score 1-10, general_score 1-10,
  primary_topic, secondary_topics[], rationale (one sentence), confidence }
```

Invalid twice -> both scores null, editor ignores.

**Two scores, one call.** `topic_score` ranks a story against others in its
own topic. `general_score` ranks it for a general reader. They answer
different questions and both are true at once: a major transfer is a 9 within
Sports and a 3 to a general reader. The site edition (6.5) ranks on
`general_score`, which is what the single `score` always meant. The app's
per-user allocator (14.4) ranks on `topic_score`, because a subscriber who
chose one topic is asking what matters *inside* that topic.

This split exists because the rubric that protects a shared edition destroys
a personalized one. scoring_v1 caps routine sport at 3 (decision #32), which
is correct when sport competes for 20 shared slots and fatal for a
Sports-only subscriber, whose every story would then sit under any quality
floor. Both scores come from the same call, so the split costs nothing
(decision #33).

**Primary and secondary topics.** `primary_topic` is where a story lives and
determines section placement. `secondary_topics` are the other topics it
legitimately reaches: US chip export restrictions is Tech, and also Business,
US Politics, and Regulation. Both fields draw from the same closed `Topic`
enum in `src/silver/score.py`; there is no second vocabulary (decision #34).

`silver.story_clusters`: cluster_id, ingest_date (partition), topic,
headline, summary_seed, member_ids, member_count, sources, score,
rationale, model_version, prompt_version, scored_at, topic_score,
general_score, primary_topic, secondary_topics. Every decision logged; this
table is the future eval dataset.

`score` and `topic` are retained and written on every row as
`score = general_score` and `topic = primary_topic`. They are the columns the
editor and every stage downstream of it read, so the site path is unchanged
by this addition. New readers use the new columns; nothing is migrated and no
published edition is invalidated (decision #17).

The partition write is a full-partition overwrite, a compare-and-swap under
Iceberg optimistic concurrency against the snapshot the handle was loaded
from before the scoring pass. A concurrent committer (the archival partition
drop in 6.9 is the one other mutator of this table) can advance the snapshot
in that window and make the commit raise `CommitFailedException`. On a lost
race the write reloads the table and retries a bounded number of times, and
only then surfaces `write_failed` (section 8). This is what makes 6.2's
"overlapping runs are harmless" true for the silver overwrite, not only for
the append-only bronze table.

### 6.5 Edition generation (two AI stages + gate)

**Scope.** This section specifies the **site edition**: one edition a day,
curated by the editor, the same for every reader. It continues unchanged. The
app's per-user newsletter is specified in section 14; it shares the writer
stage, the readability gate, and the story text, but replaces the editor with
a deterministic allocator (14.4). The two paths coexist and neither is
downstream of the other (decision #37).

**Stage 1, Editor agent (Sonnet-class, one call).** Reads today's clusters
via DuckDB. Applies editorial policy (prompts/editor_v1.md, which includes
prompts/voice.md):
- Section skeleton: Tech, AI, Business, Finance, US Politics, World,
  Regulation, Science, Cyber (optional), Sports.
- Budget 15-20 stories, min 2 / max 4 per section, global ranking. The
  upper bound of 20 is enforced on the editor *response* (retryable),
  mirroring the headline-names-a-section rule, so an over-count retries
  once with the error rather than degrading straight to a fallback. The
  assembled `Edition` re-checks the same ceiling as the authority on the
  published artifact; it is defense-in-depth, not the first line of
  enforcement. The 15-20 target and the hard 20 ceiling are stated in the
  per-call editor message, not only in the static policy, so the model
  counts against a concrete total while it fills the available sections.
  key_point topics use the short topic codes (the same code shown on each
  candidate story), which differ from the section display names; the editor
  is told this explicitly.
  The skeleton's size is bounded by this ceiling. Ten sections at the
  2-story minimum is exactly 20, so the current skeleton fits with zero
  headroom. An eleventh section would need 22 and cannot be added without
  first raising the ceiling or the per-section minimum (decision #32).
- Dead sections collapse into "briefly"; 3+ dead sections -> shrink the
  edition; broadly quiet day -> edition_type "quiet" with a 3-point glance.
- Outputs the edition core: metadata, key_points, per-story title +
  one-line summary + sources, briefly list.

**Continuing coverage (code, before the editor call).** A candidate cluster
is *continuing coverage* if it semantically matches a cluster published in
gold within `continuing_coverage_lookback_days`, using the M2 embedding
model at `cluster_threshold`. Same retrieval as stage 2, reusing
`retrieve_prior_mentions`; the difference is that it now runs before stage 1
as well, over all candidates rather than only selected stories. It is
computed once per edition and shared by both stages.

Prior coverage is a retrieval fact, not a model judgment, so it is computed
by deterministic code and handed to the editor (rule zero). Each candidate
carries a `prior_coverage` block: the dates it was covered, and the headline
as published on each.

The editor may still lead with continuing coverage. A developing story is
often the most important thing that happened. What it may not do is restate
the original event: when the top-ranked story is continuing coverage,
`headline_of_the_day` must name what is new today.

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

**Model class.** Sonnet-class. The writer is the stage that produces the
product's differentiator (decision #14, DESIGN.md section 8), and it is also
the stage where a failure is invisible downstream: the readability gate
measures grade level and schema validation checks shape, so neither catches a
specific that was never in the grounding. Moving to a Haiku-class model is a
live question (section 11) and is decided by measured eval against
`silver.story_clusters`, never by estimate.

**Prompt caching (both paths).** The writer's static prefix, prompts/
writer_v1.md plus prompts/voice.md, is byte-identical on every call, so it is
cached exactly as the scoring call's prefix is (6.4). This is a pure saving
with no behavioral change and applies whether the call is synchronous or
batched.

**Batch API, where and only where there is no deadline.** The writer stage is
submitted through the Batch API when it runs outside the publish window, which
is the continuous story writing that feeds the app (14.1). Nobody is waiting
on those calls, and the discount is roughly half.

It is **not** used inside the publish window. The site publishes against a
fixed target (6.8) and the Batch API trades latency for price, returning
within hours rather than seconds. Batching the stage that a deadline depends
on would convert a price optimization into a timeliness defect, which section
8 already measures and decision #31 already shows is the expensive kind of
failure.

The two are reconciled by reuse rather than by choosing: a story already
written by the continuous batch path is not rewritten for the edition, so the
site increasingly draws on work that was already bought at the batch price. A
story the edition needs that has no article yet is written synchronously. If a
submitted batch has not returned when the publish window opens, the affected
stories are re-issued synchronously rather than waited on, so decision #26's
guarantee that a day always publishes never depends on batch latency
(decision #43).

**Readability gate (code, editor/readability.py).** Flesch-Kincaid over
all generated text. Edition average must be grade <= 9. If over: one
automatic revision pass with failing sentences listed; if still over,
publish anyway and flag in the run log (availability beats perfection,
but the flag is reviewed).

**Headline repetition gate (code, editor/headline_gate.py).** Today's
`headline_of_the_day` is compared against the headline of every edition
published in the previous `continuing_coverage_lookback_days`. The gate
fires only on a **conjunction**: the two headlines are similar at or above
`headline_repeat_threshold`, **and** the story behind today's headline is
continuing coverage of the story behind the earlier one.

Both halves are required because headline text alone is not sufficient
evidence. The embedding captures a headline's shape and topic rather than
its event, so "judge blocks a merger" and "judge approves a merger" score
0.836 against each other. Requiring story identity as well distinguishes a
restatement from a structurally similar but unrelated headline, at no extra
cost: the continuing-coverage map is already computed.

The comparison excludes the target date itself, so re-running a published
date never flags an edition against its own headline, and skips fallback
editions, which carry no `headline_of_the_day`.

On a fire: one editor retry with the offending headline and the reason
included, per rule zero. If the second response also fires, publish anyway
and set `headline_repeat_flag` in the run log. This mirrors the readability
gate: availability beats perfection, and the flag is reviewed. A repeated
headline is a quality defect, not a correctness defect, and is not worth
failing an edition over.

**edition.json (canonical schema, JSON Schema in editor/schema.py):**

```json
{
  "date": "2026-07-19",
  "edition_number": 1,
  "edition_type": "normal | quiet | fallback",
  "headline_of_the_day": "string",
  "headline_cluster_id": "string | null",
  "headline_rationale": "string | null, <= 200 chars, never rendered",
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
  "briefly": [ {"cluster_id": "string", "title": "string",
                 "url": "string", "topic": "string"} ],
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

`headline_cluster_id` names the cluster the edition leads with, and
`headline_rationale` is the editor's one-line reason for the choice. The
rationale is stored in gold and never rendered on the site or read by a
later stage; it exists so a headline decision is answerable after the fact.

The rule that the headline names a story published as a card is enforced on
the **editor response**, not on the assembled edition. On the response the
rule is retryable, so a model slip costs one retry. On the assembled edition
it would cost the day its full page and degrade it to a fallback (section 7),
which is a real page but a much thinner one. Both fields are nullable on the
edition because
assembly can move a section into `briefly` when it cannot field two stories;
if that claims the headline's own story, code nulls the id and logs it
rather than failing the edition. Fallback editions carry neither field.

`cluster_id` on briefly items is required for every edition from the first
one published after this rule landed. It is what makes briefly coverage
findable again by gold retrieval (6.9); without it a story that ran only in
briefly is invisible to any later lookup. Readers of historical editions
treat a missing briefly cluster_id as absent rather than as an error, so
editions published before the rule keep validating and are never rewritten
(decision #17).

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

**Single voice, rendered per story.** Audio is one narrator, Norm, reading
discrete self-contained story segments. It is **not** a two-host dialogue and
is **not** rendered per edition or per user. This supersedes the multi-speaker
half of decision #4; Gemini TTS behind a swappable interface is unchanged
(decision #44).

audio/script.py: one small model call per story adapts the story's `article`
block for speech (prompts/audio_script_v1.md + voice.md). Whether this call is
needed at all is an open question (section 11): the article is already written
in Norm's voice at grade 9, and a narrator may need only mechanical adaptation
(numbers, dates, and symbols spoken rather than written), which is code.

audio/tts.py: single-speaker TTS, Gemini behind a swappable interface. One
clip per story, written to R2 and referenced by `audio.url` on the story
record (14.1). The repo never stores audio.

**A story clip is written once and reused by everyone.** This is 14.1's
property applied to the most expensive stage in the system. Per-user rendering
at 1,000 users is roughly forty to seventy times the cost of per-story
rendering and, unlike it, grows with every user added. Per-user TTS is a
design defect, not a quality tier.

**Segments must be self-contained.** A clip opens and closes without
depending on what plays before or after it, because the same clip appears at
different positions in different listeners' feeds. This is why the format is
single voice: a dialogue flows across story boundaries and cannot be recut,
which is the constraint that made per-story clips impossible before.

**Rendering is lazy.** A clip is rendered on first request rather than for
every written story, since most stories are never listened to. The lead story
and the highest `general_score` stories are pre-rendered so the common case is
immediate; the tail renders on demand. A clip that does not exist yet is not
an error: `audio` is nullable on the story record and the text is always
readable.

**Cohesion without per-user rendering.** A concatenated feed is assembled from
three kinds of reusable audio plus the story clips:

- Topic announcements, one pre-rendered clip per topic in the closed `Topic`
  enum, reused indefinitely.
- Fixed opening and closing segments.
- The personalized intro (14.5), which is already generated as text and cached
  by a hash of the ordered story-ID set. Its audio is cached under the same
  key, so listeners with the same stories share one render. This is the only
  per-listener audio, it is a few seconds long, and it inherits an existing
  cache rather than introducing a new per-user cost.

**Both paths consume the same clips.** The site's daily episode is the
concatenation of that edition's story clips, published at
/audio/YYYY-MM-DD.mp3 exactly as before, so the podcast feed and enclosure
URLs are unchanged and decision #20's promise that subscriber-facing URLs
never move is unaffected. The app's per-user listen is the same concatenation
over that user's selected stories.

The audio job's ai_cost_estimate_usd (section 8) is the sum of any script
model calls and the Gemini TTS renders, each render estimated from the TTS
response's token usage and the per-token prices in config/pipeline.yaml
(audio.tts_price_input_per_mtok, audio.tts_price_output_per_mtok). Because
clips are reused, the per-edition figure counts only renders newly performed
for that edition, not the audio it replayed.

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

An external scheduler also calls `workflow_dispatch` through the API per 6.11,
setting the `source` input to `worker`. It is subject to this same gate with
no exceptions, so it changes when the publish is reliably attempted and never
whether more than one edition can exist for a date. In practice it is the
trigger that usually publishes, because GitHub's crons do not arrive early
enough to meet the 06:00 ET target (6.11).

### 6.9 Archival job

After deploy: rewrite today's bronze and silver partitions into
gold.history (Iceberg, compacted Parquet, partitioned by month), store the
day's edition.json verbatim in gold, drop today's bronze/silver
partitions, expire snapshots older than 7 days. Gold is the permanent
record and the writer stage's background retrieval source.

A cluster counts as covered if it appeared in `sections[].stories[]` **or**
in `briefly`. A briefly line is thinner coverage than a card, but it is
coverage: a story the newsletter has already mentioned is not new to the
reader. Retrieval that reads only the section cards under-reports what was
published and will re-offer a story the reader has already seen.

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

### 6.11 External publish trigger

GitHub's scheduled events cannot meet 6.8's 06:00 ET target. Measured on this
repo from 2026-07-21 to 2026-07-27, the `30 9` cron was created between 82 and
192 minutes after its target on every single day, and the `30 10` cron between
69 and 173 minutes. No firing was ever dropped: all 14 scheduled runs in that
window were delivered. The defect is lateness, not loss, and it is unbounded
and not tunable from inside GitHub. Publication landed between 07:15 and 08:52
ET, so 6.8's "live by 06:00 ET" has never actually held.

A Cloudflare Worker Cron Trigger, running on the Cloudflare account that
already holds R2, therefore also starts the publish. It calls the workflow
dispatch endpoint, `POST /repos/{owner}/{repo}/actions/workflows/publish.yml/
dispatches`, on `main`. The two schedulers are independent providers, so the
publish now depends on neither one alone.

**Why workflow dispatch and not repository dispatch.** Both would work. The
deciding factor is the token: GitHub grants the repository-dispatch endpoint
under `Contents: write`, which also permits writing and deleting files,
creating commits and refs, merging pull requests and cutting releases. The
workflow-dispatch endpoint needs only `Actions: write`, which can start
workflows and nothing else. This credential is the one that lives outside
GitHub, in a third-party service, and the pipeline it starts runs with the
Anthropic, Gemini and R2 secrets, so a token able to modify pipeline code is
the largest blast radius in the system. Least privilege wins, and the cost is
one workflow input (below).

The Worker fires three times daily, at 09:35, 10:35 and 11:35 UTC. The first
two cover the DST pair exactly as GitHub's crons do, one of them always
landing 5 minutes after the window opens. The third is a single retry. GitHub's
own cron, arriving around 11:30 UTC on a typical day, is the final backstop.

The Worker holds no schedule logic, no DST logic, and no knowledge of whether
today is already published. It performs exactly one action: an authenticated
POST on a timer. Every decision stays in `src/schedule.py` where the tests pin
it. This follows the precedent 6.8 already set by keeping the DST rules in
Python rather than duplicating them in YAML; a second copy living in
JavaScript would be the same mistake in a new language.

**No gate change is required, and none is permitted.** The 6.8 gate already
produces the correct behavior for every case:

| situation | gate result |
|-----------|-------------|
| fires before 05:30 ET (the EST-side firing during EDT) | no-op, window closed |
| a GitHub cron already published today | no-op, already committed |
| GitHub's cron has not arrived yet, or was dropped | publishes |
| a second or third Worker firing after a successful one | no-op, already committed |

This was verified live before the trigger existed. On 2026-07-27 the day was
published by a manual dispatch at 12:21 UTC, and both GitHub crons then
arrived very late, at 12:42 and 13:23 UTC. Each ran its gate and skipped the
`publish` job against the already-committed date. Adding a third trigger is
safe for the same reason a late cron already is.

**Trigger provenance.** Because the Worker uses the same `workflow_dispatch`
event a human does, the event name alone cannot tell them apart, and that
distinction is load-bearing: a dead Worker is otherwise invisible behind a
working cron (section 8), and section 13's migration exit criterion turns on
it. The workflow therefore carries a `source` input, defaulting to `manual`,
which the Worker sets to `worker`. The `site` run_log row records
`github.event.inputs.source` when present and `github.event_name` otherwise,
giving three distinct values: `worker`, `manual`, and `schedule`.

**On `force`.** The Worker never sends it, and the input's declared default is
`false`, so a dispatch does not bypass the window or the idempotency check.
This is a weaker guarantee than the structural one repository dispatch would
have given, where the field simply does not exist, and it is worth stating
plainly rather than glossing: a stolen token could set `force: true`. The harm
ceiling is a duplicate publish of a date that is already published, which
decision #17 already prevents from overwriting a real edition. That is a much
smaller exposure than the `Contents: write` token the alternative required.

**Credential.** The Worker authenticates with a fine-grained GitHub personal
access token scoped to this repository alone, with a single permission,
`Actions: read and write`. It is stored as a Cloudflare Worker secret via
`wrangler secret put` and is never written to a file, committed, or logged
(6.10). Token expiry is a real failure mode: an expired token silently returns
publication to GitHub's cron timing rather than failing anything, which is why
sustained lateness is the signal that watches it (section 8). The expiry date
is recorded in SETUP.md, set to the longest lifetime GitHub allows for a
fine-grained token (verify the current maximum when issuing it, as that policy
has changed before), and the token is reissued during the section 13 migration
along with the other credentials.

A GitHub App was considered and rejected for v1. It would not expire, and it
would survive the section 13 org transfer more cleanly. It was rejected on
failure modes rather than on principle: JWT signing is authentication plumbing
and encodes no scheduling rule, so it does not actually conflict with the
no-logic rule above. The objection is that it puts roughly 40 lines of RS256
signing into the one component with no test suite, in the one language the
project does not otherwise use, and it fails with a 401, the same symptom as
an expired token but harder to diagnose. That trades a predictable failure on
a known date for an unpredictable one at any time. The expired-token case is
benign by comparison: the GitHub crons still publish, so the cost is
punctuality and not the edition.

Revisit at the section 13 migration, which is the point where the org exists,
the credential is being reissued anyway, and infrastructure stops fronting
through one personal account. If this ever gains a second maintainer, the App
becomes the correct shape.

**Expected effect.** The firing that opens the window publishes at roughly
09:45 UTC, which is 05:45 ET. In the normal case the Worker becomes the
trigger that actually publishes and GitHub's crons become redundant. That is
the point: it is what makes 6.8's "live by 06:00 ET" true rather than
aspirational.

## 7. Failure behavior

| Failure                        | Behavior                                        |
|--------------------------------|--------------------------------------------------|
| One adapter fails              | Log, skip, continue                              |
| All sources return nothing     | run_log `failed` + healthchecks `/fail` (blind collector) |
| Missed collector cycles        | Next cycle backfills via `since`; bronze dedups  |
| Silver write loses a commit race | Reload table, retry bounded; only then run_log `write_failed` |
| One story's article fails 2x   | Story publishes without article block            |
| Editor output invalid 2x       | Publish fallback edition (edition_type fallback) |
| Edition assembly raises        | Publish fallback edition; run_log `partial`      |
| Readability revision raises    | Publish the edition as assembled; run_log `partial` |
| Zero/near-zero data at 6am     | Publish quiet edition                            |
| Readability gate fails 2x      | Publish, flag in run log                         |
| Headline repeats a recent one 2x | Publish, flag in run log                       |
| TTS fails                      | Publish without audio row; log                   |
| Deploy fails                   | healthchecks.io alert (missing ping)             |
| Publish cron late or dropped   | External dispatch (6.11) publishes; the gate makes the later cron a no-op |
| External trigger dead          | GitHub cron still publishes, late; surfaced as sustained lateness (section 8), never as a missed day |

The fallback edition is a real page (DESIGN.md NoticeBanner + RankedList):
notice in Norm's voice, top 10 clusters by score, titles and links. The
site never silently skips a day and never shows a broken page.

Decision #8 is a floor, not a best effort. Once the pipeline has candidate
contexts for the day, every path out of edition generation ends in a written
edition. A normal or quiet edition that cannot be assembled publishes the
fallback instead; a revision stage that raises publishes the edition as
assembled, because an already validated edition is strictly better than the
fallback that would replace it. Code records the exception type in the run
log and marks the run `partial`. A fallback never overwrites an already
published normal or quiet edition for the same date (decision #17). Exactly
two conditions still leave a day unpublished: no candidate contexts at all,
and a failure to write the file itself.

A stage the publish workflow classes as non-blocking, the audio build being
the one such stage today, must never fail the workflow. A non-zero exit from
it publishes the edition without that stage's contribution (SPEC 7's "publish
without audio row"), rather than stranding an edition that is already built.

A degraded publication, a fallback published when a real edition was possible
(section 8's degraded reasons), is the one thing that reddens the publish
workflow after a successful deploy. This is a signal, not a failure of the
publish: the site is live and healthchecks is green, and the red Actions run
exists only to alert that the day's edition was thinner than its data
allowed. It never affects the published page.

## 8. Observability

**`ops.run_log` (Iceberg, partitioned by run_date).** One row per job run.
Written by every job, including failed ones, and including a job that fails
during setup before its main work: an unreachable catalog is a logged
`failed` row, never a missing one. A job that cannot write its own row is
itself a failure surfaced by the dead man's switch.

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
| headline_repeat_flag | boolean? | editor job only, per 6.5 (gate fired twice) |
| reasons            | string?   | JSON array of enumerated reason codes (below); null when there is nothing to report |
| notes              | string?   | nullable                                  |
| run_date           | date      | partition column                          |

`status` is `partial` when the job completed but something was less than
ideal. That covers a wide range, from a single story missing its article to
the whole edition collapsing to a link list, so `status` alone cannot be
alerted on: in production it is the editor's normal state. The `reasons`
column is what makes `partial` legible.

**Reason codes.** `reasons` holds a JSON array of codes from a closed set,
stored the same way `adapter_metrics` stores JSON in a string column. `notes`
keeps the human-readable detail beside it. The set is closed on purpose: a
new cause of a `partial` or `failed` run adds a code here, it does not go to
free text. A run may carry more than one code.

| code | meaning | degraded |
|------|---------|----------|
| `editor_invalid_fallback` | the editor's output failed validation twice, so a fallback published in place of a real edition | yes |
| `assembly_fallback` | edition assembly raised, so a fallback published (decision #26) | yes |
| `thin_day_fallback` | too little usable data for a normal or quiet edition | no |
| `headline_repeat` | the headline gate fired (6.5) | no |
| `thin_grounding` | one or more stories published without a full article | no |
| `article_validation_failed` | one or more articles failed validation twice | no |
| `readability_exceeded` | the readability gate was still over the limit after revision | no |
| `readability_raised` | the readability revision stage raised and the edition published as assembled | no |
| `adapters_failed` | one or more source adapters errored and were skipped | no |
| `no_items` | a collection cycle fetched zero items across all sources | no |
| `null_scores` | one or more clusters were stored with a null score | no |
| `no_edition` | audio or archive found no edition.json for the date | no |
| `audio_missing` | the script or TTS produced no audio; the edition published without it | no |
| `write_failed` | the Iceberg write raised (for the silver overwrite, after its bounded retry was exhausted) | no |
| `run_failed` | a setup failure or unhandled error, logged by the run wrapper | no |

**Degraded.** A run is *degraded* when its `reasons` intersect the degraded
subset, `{editor_invalid_fallback, assembly_fallback}`. A degraded
publication is one where readers received materially less than the day's data
supported: a bare list of links where a full edition was possible. A
thin-day fallback is deliberately not degraded, because too little news is
correct behavior rather than a defect. "Was today degraded" is therefore a
query over `reasons`, not a separate stored flag that could drift from it.

**Timeliness.** SPEC 6.8 opens the publish window at 05:30 ET so the site is
live by 06:00 ET. That is measured rather than asserted: a publication is
*late* when the `site` job's `ended_at`, converted to Eastern local time,
falls after 06:00 on its own date. Like degraded, late is a derived query over
`run_log` and not a stored flag, so it cannot drift from the data
(decision #27).

Late is not degraded and does not redden the Actions run. The reader received a
complete edition, only later than intended, so it carries no reason code: the
closed set above describes what the reader got, not when they got it. Lateness
is reviewed in the weekly 10-minute review alongside cluster quality.

Sustained lateness is also the health signal for the external trigger (6.11).
Because either scheduler alone publishes, a dead Worker or an expired token
fails nothing: it silently returns publication to GitHub's cron timing, which
has run 82 to 192 minutes late. A run of consecutive late publications is the
only routine signal that says the dispatch path has stopped working.

This measure starts life failing. Every day from 2026-07-21 to 2026-07-27 was
late under this definition, landing between 07:15 and 08:52 ET. That is the
honest baseline the external trigger exists to fix, not an untested target.

**Two independent signals.** healthchecks answers one question, "did the site
publish," and nothing else is layered onto it: a red check means the site did
not publish, a green check means it did. Whether a published edition was
degraded is answered separately, by a failed GitHub Actions run at the end of
the publish workflow (6.8): the deploy has already happened and healthchecks
is already green, so only the Actions run goes red, which alerts by email
without touching the published page or the dead man's switch.

healthchecks.io:
one check for 6am publish, one for the collector cadence. The collector
pings `/fail` when a cycle fetches zero items across all sources, not only
when the bronze write fails, so the cadence check catches a running-but-blind
collector (a source-wide outage or a datacenter-IP block), not just a stalled
process or an R2 failure. Weekly 10-minute review: cluster quality, score
distribution, readability flags; tune cluster_threshold and rubric anchors.

## 9. Cost budget (monthly, target < $25)

| Line item                                   | Estimate |
|---------------------------------------------|----------|
| Scoring (Haiku-class, cached)               | $4-8     |
| Editor + writer stage (per-story articles, cached; batched outside the publish window) | $6-10 |
| Audio: per-story clips, single voice, rendered once and reused | $3-6 for the site edition; see 6.7 for app scaling |
| Embeddings (local)                          | $0       |
| R2 + catalog, Actions, Pages, monitoring, trigger Worker | ~$0 |
| Buffer                                      | $2-4     |

Levers if over: max_items_per_run, re-scoring rule, article length.

## 10. Decision log

| #  | Decision |
|----|----------|
| 1  | Multi-source, no X in v1 (cost + redistribution compliance) |
| 2  | Cluster threshold 0.82, config-driven, observed for 2 weeks |
| 3  | 15-20 stories, 2-4 per section, dead sections -> Briefly |
| 4  | Gemini multi-speaker TTS behind a swappable interface. **Multi-speaker superseded by #44** (single voice, per-story clips); Gemini behind a swappable interface stands |
| 5  | Collector runs on GitHub Actions every 3h (`collect.yml`), same entry point, idempotent. A local machine is an optional supplement, not relied on (a sleeping MacBook Air caused the 2026-07-20 gap) |
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
| 23 | Briefly counts as published coverage. Briefly items carry a `cluster_id` so gold retrieval can find them; editions published before this rule keep validating without one and are never rewritten |
| 24 | Continuing coverage is surfaced to the editor, not suppressed. Leading with a developing story is allowed; restating yesterday's headline is not. The gate fires only on same-sentence AND same-story, and flags rather than fails |
| 25 | The edition names the cluster its headline is about and records why. Enforced on the editor response, never on the assembled edition, because a rejected response is retryable while a rejected edition degrades to a fallback |
| 26 | Any failure after candidate selection produces a published edition, never an empty day. A stage that has not yet produced an edition degrades to the fallback; a stage that already holds a valid one publishes it unrevised. Enforced at the orchestration points rather than at each failure site, so a future required field on the edition schema can cost quality but never the day |
| 27 | `run_log.status` is too coarse to alert on (`partial` is the editor's normal state), so `run_log` carries a closed set of enumerated `reasons` codes (section 8). "Degraded" is a derived query over a degraded subset, not a stored flag, so it cannot drift. A degraded publication is alerted by reddening the GitHub Actions run after a successful deploy, never by healthchecks, which stays a pure published-or-not signal |
| 28 | The 15-20 story budget's upper bound (20) is enforced on the editor response, not only on the assembled Edition. On 2026-07-24 the editor curated 23 stories; the ceiling lived only on the non-retryable Edition, so a self-correctable over-count degraded the day to `assembly_fallback`. Enforcing it on the retryable response lets `call_validated` return the error and trim on retry; a second failure still falls to `editor_invalid_fallback`. Extends decision #25's rule to the story count |
| 29 | The editor is given the per-edition story budget (15-20 target, hard 20 ceiling) and the valid key_point topic codes in the per-call message, not only in the static policy. On 2026-07-24 a busy day with no total-story anchor over-produced 23 stories, and a separate key_point topic slip (`Cybersecurity` for `Cyber`) consumed the other attempt, so a self-correctable over-count fell to a fallback. The prompt now anchors the count where the model decides it and points topic tagging at the short code each candidate already carries. Complements #28, which made the ceiling retryable |
| 30 | The silver partition write is a full-partition overwrite, not append-only, so unlike bronze it can lose an Iceberg optimistic-concurrency race. On 2026-07-24 a `collect` run scored all 103 clusters and then raised `CommitFailedException` on the commit (the archival partition drop the likely counterparty). The overwrite now reloads the table and retries a bounded number of times before surfacing `write_failed`, which makes decision #5's idempotent-overlap promise (SPEC 6.2) true for the silver overwrite and not only for the append-only bronze table. Scoped to the silver overwrite: bronze and run_log are append-only and rarely conflict, and the closed reason-code set is unchanged (`write_failed` now means the write raised and retries were exhausted) |

| 31 | GitHub's scheduler cannot meet 6.8's 06:00 ET target. Measured 2026-07-21 to 2026-07-27, the publish crons were created 82 to 192 minutes after their target on every single day, so publication landed 07:15 to 08:52 ET and the stated goal never held. No firing was ever dropped: all 14 scheduled runs arrived, so this is a timeliness defect and not a recovery one, and decision #7 already makes lateness safe rather than fatal. The delay is unbounded and not tunable from inside GitHub, so an independent Cloudflare Worker Cron Trigger also calls the workflow dispatch endpoint (6.11), firing 5 minutes after the window opens. It uses workflow dispatch rather than repository dispatch because GitHub grants the latter under `Contents: write`, which also permits committing code, while the former needs only `Actions: write`; this is the one credential held outside GitHub, so least privilege decides it. The existing window-plus-idempotency gate handles the trigger with no change, which is what keeps the scheduling rules in tested Python rather than a second copy in JavaScript. Verified live on 2026-07-27, when a manual publish at 12:21 UTC was followed by both crons arriving at 12:42 and 13:23 UTC and each correctly skipping the already-committed date. The GitHub crons are kept rather than replaced, because the gate makes redundancy free and two independent schedulers beat one reliable-looking one |

| 32 | Sports is the tenth section. The topic vocabulary is a closed enum (`Topic` in `src/silver/score.py`, mirrored in the response schema), so the scoring call cannot decline a story: a sports item is not dropped, it is filed under a wrong topic, most likely World or Business, where it competes for a real section slot under a false label. Adding sports feeds therefore required the vocabulary change first, or the failure mode would have been section pollution rather than clean rejection. No budget constant moved: `plan_sections` fields a section at 2+ stories, so ten sections at the minimum is exactly the 20 ceiling, and measured across the first 13 editions only 4 to 6 sections were ever alive at once, against totals of 9 to 16 stories on a 15-20 target. The edition was under-supplied rather than oversubscribed, which is also why more sources were worth adding. The zero headroom is real though, so an eleventh section (Health was the candidate) needs 22 and must raise the ceiling or the per-section minimum first; that is recorded in 6.5 rather than solved. Sports renders last because `SECTION_ORDER` derives from `TOPICS` order, making the editorial judgment a one-line consequence of the constant. The load-bearing part is the rubric, not the enum: the wave-1 feeds carry roughly 95 items a day against about 175 clusters from all 34 prior sources combined, and most sports volume is fixtures, transfer rumors, betting lines, and fantasy advice, so scoring_v1 caps routine sport at 3 and requires significance beyond the result to clear 6. Without that cap the section would have crowded out news on the shared 1-10 scale. Sources start at three, not the six vetted, so the effect on candidate volume is observed before expanding |

| 33 | Scoring returns two scores from one call: `topic_score` (rank within the story's own topic) and `general_score` (rank for a general reader). The single `score` was correct for one shared edition and breaks personalization, because the rubric that protects a shared edition destroys a per-user one. scoring_v1 caps routine sport at 3 and requires significance beyond the result to clear 6 (decision #32), which is right when sport competes for 20 shared slots against real news. For a subscriber who chose Sports and nothing else, every story in their newsletter then scores 3: any quality floor empties their newsletter permanently, and removing the floor degrades quality for everyone else. The two scores are not a compromise between those, they are answers to two different questions, and both are true at once. Both come from the same call against the same rubric, so the split costs no additional tokens. Decided before the app data layer is built because changing it later means re-scoring the entire history rather than adding a field; the cost is a prompt and schema change today against a backfill of every cluster ever scored in six months |
| 34 | A story cluster carries `primary_topic` plus `secondary_topics[]`, replacing the single `topic`. One topic per story was sufficient when placement was the only consumer: a story goes in exactly one section. Under per-user selection the field also decides reach, and the two are not the same question. US chip export restrictions is genuinely Tech, Business, US Politics, and Regulation; filed as Tech alone, every Business subscriber who wanted it never sees it, and across a few hundred stories a day personalization thins out for no reason other than a schema limit. `primary_topic` keeps its placement meaning unchanged, so section assignment in 6.5 is unaffected. Both fields draw from the same closed `Topic` enum in `src/silver/score.py`, mirrored in the response schema, so the scoring call still cannot invent a topic and decision #32's rejection-versus-pollution reasoning holds for both fields |
| 35 | Embeddings become a cache keyed by `(item_id, model_version)`, amending 6.4 rather than reversing it. Storing nothing was correct while embeddings were computed twice a day for clustering, the headline gate, and gold retrieval; the property that a model change costs a threshold re-calibration and no data migration is worth keeping, and it survives here. A cache is not a schema: a miss recomputes exactly as before, so no stage may treat a stored vector as required input, and a model change invalidates by version rather than migrating. What changed is the read pattern, not the value of the vectors: the app matches stories against user topics continuously rather than once per edition, which turns recomputation from a negligible cost into the dominant cost of a per-user query. `model_version` is stored with every vector so a stale entry can never be served against a newer model, which is what makes invalidation safe to do by deletion |
| 36 | Personal data never enters the data lake. Accounts, chosen topics, read time, seen-stories, and push tokens live in Postgres; bronze, silver, and gold hold only news. The performance argument (a lake answers "summarize a million rows", a phone asks "give me this one user's settings in 50 ms") is real but secondary. The deciding one is deletion: Apple Guideline 5.1.1(v) requires in-app account deletion and privacy law requires it to be actual deletion, which is one `DELETE` in Postgres and a genuinely hard problem in an append-only Iceberg table with snapshot time travel, where the old value remains readable in prior snapshots by design. Keeping personal data out entirely avoids the problem rather than solving it, and preserves decision #17's promise that a committed record is never rewritten |
| 37 | The allocator (14.4) replaces the editor for **app newsletters only**. The editor remains the site's curator and 6.5 is unchanged. The two paths coexist, share the writer stage, the readability gate, and the story text, and neither is downstream of the other. An AI editor call per user is the design this architecture exists to avoid: it scales cost linearly with users while the story writing does not, so at 1,000 users the per-user call dominates the entire bill. As deterministic code the same job is also testable, predictable, and cheaper to reason about, which is rule zero's preference anyway. Keeping the editor rather than porting the site onto the allocator is deliberate: the site is a working, publishing system whose 14-day streak is still being established, and replacing its curator would restart that clock for no product gain |

| 38 | Per-user delivery resolves the next read time from `read_time_local` plus IANA `timezone` on every scheduler pass, and never stores a precomputed UTC instant. A stored UTC timestamp is correct until the next daylight-saving transition and then silently wrong for every affected user, which is the same defect 6.8 already handles for the single publish time, except distributed across the user base and therefore much harder to notice. The two ambiguous cases are specified rather than left to a library default: a read time inside the skipped spring-forward hour delivers at the first valid instant after the gap, and a read time inside the repeated fall-back hour delivers on the first occurrence only. Assembly is idempotent on `(user_id, local_date)`, which is the same window-plus-idempotency shape as 6.8 and is what makes an overlapping or late loop harmless rather than a double delivery. Lateness is explicitly not failure: section 8's timeliness measure is a property of a single scheduled publish and has no meaning when every user has their own deadline |
| 39 | The app API is versioned under `/v1/` from the first public release, and backward compatibility inside a version is a hard constraint. The site never needed this because both ends shipped together and a browser always loads current code. An App Store binary does not: old clients live in the wild indefinitely and a device that never updates keeps calling this API for months, so a removed or retyped field breaks users who cannot be reached. Within a version, fields may be added or become nullable but never removed, renamed, or redefined; anything else is `/v2/`. A configurable minimum supported version gives a structured upgrade-required response rather than a broken screen, and is configuration rather than code so raising it needs no deploy. Identity is always resolved from the authentication token and never accepted as a request parameter |
| 40 | The chat and story tracker run on Anthropic Managed Agents, and the Story MCP server is the only path from the agent to any data. The platform is chosen for three capabilities the tracker requires and would otherwise have to be built: code execution to compute and chart how coverage moved, memory persisting across sessions, and a server-side scheduler for "tell me when this develops". Runtime price is not the deciding factor at v1 scale. The MCP boundary is a security decision, not an architectural preference: the sandbox holds no database credentials, every tool is scoped server-side to one `user_id`, and the client never supplies a prompt, because a client-supplied prompt is prompt injection and metered-cost abuse at once. The whole branch sits behind a server-side feature flag, since it depends on a beta API and ships inside an App Store binary that cannot be recalled |
| 41 | Agent chat output is prose rendered to a human and therefore does not satisfy rule zero's schema-validated-JSON requirement, in the same way TTS does not. The rule's intent is preserved by a boundary instead of a schema: agent output is never written into a story record, a newsletter record, or any table, and is never read by a later pipeline stage. It is displayed and discarded. Tool calls the agent makes are structured and validated normally. This keeps rule zero's actual guarantee intact, which is that no unvalidated model output enters the deterministic data path. A future feature wanting agent output to become stored data is a new spec question and not an extension of this one |
| 42 | Mobile releases run from GitHub Actions rather than Expo's own pipeline, so that one system answers what shipped and when, alongside the backend that already lives there. `EXPO_TOKEN` is an Actions secret under rule 5. The over-the-air and full-build split is recorded because it changes what "deployed to production" means: JavaScript and asset changes reach users in minutes with no review, while anything touching native code needs a store submission and days of review. Treating those as one release path is how a hotfix gets planned as if it were instant when it is not |

| 43 | The writer stage caches its static prefix and is batched only outside the publish window. Caching is unconditional: prompts/writer_v1.md plus prompts/voice.md are byte-identical on every call, so this is a saving with no behavioral change, matching what 6.4 already does for scoring. Batching is conditional because the Batch API trades latency for roughly half the price, and the site publishes against a fixed target (6.8) that section 8 measures and decision #31 already showed is the expensive thing to miss. Continuous story writing for the app (14.1) has no deadline and takes the discount; the publish window does not. The two paths reconcile by reuse rather than by choosing a side: a story already written by the batch path is not rewritten for the edition, so the edition increasingly consumes work bought at the batch price, and only a story with no article yet is written synchronously. A batch that has not returned when the window opens is re-issued synchronously rather than waited on, so decision #26's never-an-empty-day guarantee never comes to depend on batch latency |

| 44 | Audio is a single voice reading self-contained per-story segments, superseding the multi-speaker half of decision #4. The two changes are one decision, not two: a two-host dialogue flows across story boundaries and cannot be recut, which is precisely what made per-story clips impossible, so choosing one voice is what unblocks reuse. Reuse is the point, because TTS is the most expensive stage in the system and per-user rendering at 1,000 users costs roughly forty to seventy times per-story rendering while also growing with every user added, which is the scaling property 14.1 exists to prevent. Clips render lazily on first request rather than for every written story, since most stories are never listened to, with the lead and highest `general_score` stories pre-rendered so the common case is immediate. Cohesion is recovered without per-listener rendering: topic announcements are one reusable clip per enum topic, opening and closing segments are fixed, and the only per-listener audio is the personalized intro, which is seconds long and inherits the story-ID-set cache key 14.5 already defines. A single voice also resolves an inconsistency rather than creating one: decision #11 makes Norm the editor persona, and a two-host format meant Norm plus an unnamed second party. The site episode remains the concatenation of that edition's clips at the same URL, so decision #20's guarantee that subscriber-facing URLs never move is untouched |

| 45 | The allocator distributes a user-chosen budget across their topics in proportion to a user-set weight, replacing the earlier fixed budget with per-topic minimum and maximum constants. The reason is that the two mechanisms do the same job and the constants win silently: a per-topic minimum overrides the weight the reader just set, so the setting appears to work and does not. Weights also subsume the separate rebalancing rule, because a single-topic user has a share of 1.0 by arithmetic rather than by a special case. What the constants guaranteed is preserved by other rules rather than lost: reclaim and redistribute (rule 6) stops a quiet topic wasting budget, and the `general_score` top-up (rule 7) stops a quiet user receiving a thin newsletter. A topic legitimately allocated zero stories is the reader's own instruction rather than a defect, which is why the client states that outcome in the band label rather than hiding it. The cost of the change is that determinism now depends on four tie-breaks that a fixed allocation did not need, so all four are specified and asserted rather than left to sort stability. This also converts the budget from a constant in `config/pipeline.yaml` into per-user state, which is why 14.5 snapshots the weights and targets actually used: without that record a newsletter stops being explainable the moment the reader re-weights a topic |

| 46 | The free tier is a cap on how many ranked topics run, which makes an entitlement an input to the allocator rather than a screen in front of it. This reclassifies monetization from a release-blocking question to one blocking the first line of app code, because 14.4 rule 1 cannot be written without it. The cap applies to ranked topics rather than chosen ones, and locked topics are withheld rather than discarded, so a downgrade never destroys the reader's ordering and an upgrade is not a fresh start. Entitlement is resolved server-side on every assembly and every request, for the same reason 14.7 refuses a client-supplied `user_id`: a client-asserted plan is a paywall bypass, and one shipped inside an App Store binary cannot be recalled. Assembly treats an unresolvable entitlement as the last known plan and otherwise as free, so that decision #26's per-user form never acquires a dependency on the payment system being reachable. What the tier withholds is quantity and never the writing: the readability gate, the voice standard, and the grounding rules are identical on both tiers, because degrading them for free users would trade away the one property that makes the subscription worth buying |

| 47 | Subscriptions are sold through in-app purchase rather than the direct payment path the prototype shows. Apple Guideline 3.1.1 requires IAP for digital content consumed inside the app, and a subscription to the app's own newsletter is not a borderline case. The entitlement of record is the server's, derived from a validated store transaction; a client-held receipt is evidence and never the source of truth, which is the same boundary decision #46 draws for the plan itself. Recording this as a decision rather than an implementation detail is deliberate: a direct payment path is the single most likely cause of a review rejection in the app, it is cheap to choose correctly now, and discovering it at submission costs a review cycle on a binary that has already been built and tested against the wrong assumption |

| 48 | The allocator uses two lookback windows rather than one, and breaks score ties by recency. A single window has to serve a daily reader who wants this morning's news and a returning, newly signed up, or newly re-topiced reader who wants the backlog, and those two want opposite values: 24 hours makes catch-up useless while a week makes daily reading stale. The daily window is set wider than a day on purpose, for the same reason `since_window_hours` is wider than the collector's cadence: the overlap is what stops a drifting read time or a late assembly from falling into a gap. The catch-up window stops at roughly a week because past that point the reader is browsing an archive rather than catching up, and the app offers that separately. Recency joins the ordering because scores do not age: a 9 from four days ago outranks a 6 from this morning for as long as both are eligible, so without a recency tie-break any widening of a window silently ages the newsletter for readers whose topics move slowly, and the previous `story_id` tie-break resolved that by an arbitrary string. Widening a window is close to free, since the stories are already written and stored and no AI call is involved, which is what makes this a question about staleness rather than cost. The catch-up window is bounded by the retention period rather than the reverse, because offering a backlog longer than retention promises data that has already been deleted. This also converts 14.4's existing promises about topic backfill and a new user's first newsletter from aspirations into behavior a window can actually deliver |

| 49 | The app's v1 topic menu is the ten topics already in the enum, with nothing added, renamed, merged, or retired. The prototype's twenty are recorded in 14.3 as a deferred expansion rather than adopted. The reason is that a wider menu is not a configuration change: `scoring_v1` carries anchored 3, 6, and 9 example stories for every topic, so thirteen additions are thirteen anchor sets to write and calibrate, and decision #32 is the evidence that those anchors decide outcomes rather than decorate the prompt. The prototype's merge of Business with Finance and its retirement of Regulation and Cyber also touch rows already written to `silver.story_clusters`, converting a menu change into a data migration. Shipping the existing ten costs nothing, is validated by fifteen published editions rather than chosen in the abstract, and leaves 14.4's `general_score` top-up to cover thin coverage, which is what weakens the case for many narrow topics in the first place. `Sports` is kept despite never having produced a section, because that is precisely the reader decision #33 introduced `topic_score` to reach and is therefore the clearest available evidence that the two-score change works |

| 50 | Authentication is Sign in with Apple plus email magic links, with no social logins and no passwords. Excluding social login is the load-bearing half: Apple Guideline 4.8 obliges an app offering any third-party login to also offer Sign in with Apple, so each provider added is two pieces of work plus the account reconciliation for one human arriving through two providers, while offering none leaves the app outside the guideline rather than compliant with it. Passwords are excluded because they invert the usual cost intuition: they read as the simple default while carrying reset flows, an email delivery dependency, correct hashing, rate limiting, and breach exposure, none of which a one-time link has. Apple is primary because 14.9 ships iOS first, and its private relay address is accepted as given and never resolved, so most users never hand over a real address. Email keeps a later Android release from needing a new identity system. This is the first question in section 14 to settle because everything user-scoped is defined in terms of a `user_id`, and 14.2 requires that column from the first migration rather than retrofitted |

| 51 | Feedback telemetry is instrumented in v1 before its use is decided, because it is the only open question in section 14 whose answer is destroyed by deferral: every other one can be settled later at no cost, while behavior that was not recorded cannot be recovered. Four events are recorded, and `story_skipped` is included deliberately as the negative signal, which is the one most often omitted and the only one that identifies a selection that was wrong rather than merely unread. The events are aggregated and never fed back automatically: no event adjusts a reader's weights, topics, or length, because 14.4 exists so that selection is explainable rather than emergent, and a silent second allocator would undo that. Only behavior is recorded and never subject matter as free text, which is the line between a behavior log and a profile. The rows live in Postgres with the rest of the personal data so decision #36's single-`DELETE` guarantee still holds. The cost is one table and four calls, and it is out of proportion to what it settles: the free-tier allowance, both lookback window values, and the top-up rules are currently arguable and become measurable. 14.5 already stores the other half through `topped_up`, `locked_topics`, and the `allocation` snapshot, so this completes a join rather than starting a new dataset |

| 52 | Push notification copy comes from deterministic templates filled from the newsletter record, never from a model. The reason is 14.1's flat-cost property rather than the price of the call: the per-user path holds exactly one AI call, and a generated notification is a second one. It is unusually easy to add by accident because a notification feels too small to count as a model call, which is why this is a decision rather than an implementation note. A generated string would also sit between the assembled newsletter and the reader's lock screen with nothing validating it and no gate reading it, unlike every other piece of text the system emits. Templates are additionally testable, translatable, and identical for two readers who received the same lead story, none of which a generated string is |

| 53 | The app has no edition number. The site's sequential numbering counts what the site published, which is a fact about the site rather than about any reader, and 14.2 already establishes that there is no global edition date in the app. The prototype carries the number into the masthead, the push copy, and the agent's opening line, and in each place it asserts something untrue: two readers opening on the same day did not receive the same numbered artifact. A per-user sequence was considered and rejected as worse than none, because it invents an identifier that means nothing to its owner and cannot be used to refer to anything between two readers. The local date is true, sufficient, and already stored |

| 54 | Chat in v1 is ephemeral, with no saved-conversation history. This follows from decision #41 rather than adding to it: a past-chats list is a table of agent output, which #41 forbids explicitly, so shipping the prototype's history feature would require amending #41 rather than implementing around it. Deferring keeps the rule true as written and keeps the agent shippable, since none of the feature is needed for the agent to answer questions about a reader's own stories. Taking it up later means deciding what a stored transcript is for, how long it is retained, whether decision #36's single-`DELETE` guarantee covers it, and whether the agent may read its own history back, that last one being the point at which unvalidated model output would re-enter the data path that rule zero exists to protect |

| 55 | Stories, newsletters, and seen-story history are retained for 12 months, and telemetry events for 13. Twelve months is chosen as a product decision rather than a storage one: it is what 14.10 can honestly sell as Pro archive depth, namely a reader's first year, in place of the prototype's "every newsletter ever delivered" which was never going to remain true. Storage is not the deciding factor, since stories are text and 14.5 stores identifiers rather than copies of them. The clocks for newsletters and seen-story history are tied to the story clock rather than chosen independently, because a newsletter referencing deleted stories is a broken record and remembering that a deleted story was seen serves nothing. Telemetry runs one month longer so that a full year can be compared against the same month a year earlier, which is most of why the data is worth keeping. Retention is deliberately separated from account deletion: retention is about age and runs on a schedule for everyone, while deletion is about a person, is immediate, and ignores every retention clock. Decision #36 is what keeps deletion to a single operation, and that holds only while every table containing personal data is enumerated, which is why 14.11's event table is named in 14.12 rather than left to be remembered. Deciding this now costs a configuration value and a scheduled job; deciding it after a year of accumulation costs a migration against live data |

| 56 | Top-up is bounded on both sides: a `general_score` floor of 6 and a cap of half the budget. Rule 7 reads as one sentence but decides what the product feels like for the narrowest subscribers, who are also the likeliest to leave, so its constants are specified rather than left to the implementation. The floor never yields and the budget does: when too few stories clear it the newsletter is simply shorter, because `length` is a maximum the reader chose rather than a quota to hit, and a short good newsletter beats a full padded one. Six is the site's own bar, so nothing reaches a reader that would not have reached the site. The cap exists because a full newsletter is not automatically the reader's newsletter: someone who picks Science and Space and receives eleven stories from Politics and World has a full newsletter they did not subscribe to, and at half the budget a top-up is a supplement while past half it is a substitution. Topped-up stories are labelled and grouped last rather than mixed in, because the same story shown unlabelled under a topic the reader never chose reads as a defect rather than an offer. Both values are constants tuned against 14.5's `topped_up` and 14.11's `story_skipped` rather than logic, so lowering the cap is a configuration change. Decision #26's per-user form is unaffected, since it promises a newsletter and not a full one |

## 11. Remaining open questions

- Whether briefly items get one-line summaries or titles only (v1: titles).
- GDELT adapter in v1.1.
- Whether the migration (section 13) also moves API keys to a
  project-owned email/account set, and which providers allow it cleanly.
- Whether collect gains the same external backup trigger. Approved in
  principle. It needs a staleness check so a redundant firing does not double
  metered Actions minutes, and that check is new tested logic, so it lands as
  its own addition after 6.11 proves out.

### App layer (section 14)

Grouped by what each one costs to answer late, which is not the same as how
urgent it feels.

**Blocking the first line of app code.**

- ~~Authentication~~ **Closed** by decision #50: Sign in with Apple plus email
  magic links, no social logins, no passwords. Specified in 14.2.
- ~~The topic menu~~ **Closed** by decision #49: v1 ships the existing ten.
  The prototype's twenty are recorded in 14.3 as a deferred expansion, and
  taking it up later is a rubric re-calibration plus a data migration rather
  than a configuration change. Not blocking any more.
- ~~The allocator constants~~ **Closed.** Decision #45 made the budget per
  user and removed the per-topic minimum and maximum, #48 specified the two
  lookback windows, and #56 specified the top-up floor and cap.
  `tests/test_allocator.py` now has real numbers to assert against. All of
  them are constants to be tuned against 14.5's counters and 14.11's events
  rather than re-derived, so revisiting any is a configuration change.
- ~~The free-tier topic allowance~~ **Fixed at 3 for v1** (14.10). It ships as
  written rather than staying open, because it is the single number deciding
  both how useful the free tier is and whether anyone upgrades, and neither is
  answerable in advance. It is revisited against 14.5's `locked_topics` and
  14.11's events once there are readers, which is calibration rather than an
  open specification question.

**Cannot be added retroactively, which is what makes them urgent.**

- ~~Feedback telemetry~~ **Closed** by decision #51 and specified in 14.11:
  four events, recorded in v1 before their use is decided. What remains open is
  not whether to collect but what to conclude, and that is answered by the data
  rather than in advance.
- ~~Data retention~~ **Closed** by decision #55 and specified in 14.12: 12
  months for stories, newsletters, and seen-story history, 13 for telemetry.
  This also closes the two features it gated, Pro archive depth (14.10) and
  `lookback_catchup_days` (14.4), both of which now sit comfortably inside the
  window.

**Blocking release rather than code.**

- ~~Push notification copy~~ **Closed** by decision #52: deterministic
  templates filled from the newsletter record. Specified in 14.6.
- **Monetization** is settled in shape by 14.10 and decisions #46 and #47, and
  is no longer release-blocking. Two pieces of it remain open and are listed
  where they belong rather than here: the free-tier allowance above, and
  whether the agent (14.8) is gated, which is the one component whose cost
  scales with engagement rather than news volume.
- **The Sunday retrospective (14.10).** Offered as a Pro benefit in the
  prototype and deliberately unspecified. It is a second assembly on a weekly
  cadence with its own record and its own AI call, so it is a new
  specification rather than a variation of 14.4.
- **Whether read time re-anchors when a user travels (14.2).** The client
  reports the device zone, so a user who flies to Tokyo either keeps waking to
  news at their home hour or starts receiving it at 6am local. Both are
  defensible and the choice is invisible until it happens to someone.
- **Onboarding.** What a new user sees before any topic is chosen, and how the
  first newsletter is framed given 14.4 builds it immediately rather than at
  their first read time.
- **Content moderation for the agent (14.8).** The agent will be asked about
  distressing news. Decision #41 keeps its output out of stored data, which
  bounds the blast radius but does not decide what it should decline to do.

**Decided by measurement rather than argument.**

- Whether the per-story audio script call survives at all (6.7). The article
  is already written in Norm's voice at grade 9, and a single narrator may
  need only mechanical adaptation of numbers, dates, and symbols, which is
  code rather than an AI call. Settling this removes or keeps one model call
  per story. Decided by listening to both, not by argument.
- Which voice, and whether it is the same voice for the site episode and the
  app listen (6.7). Decision #44 settles that there is one voice, not which.
- Whether the app's per-user newsletters are subject to the same timeliness
  measure as the site (section 8), given each user has their own deadline and
  there is no single publish time to be late against. 14.6 currently states
  that lateness is not failure; a per-user measure would change that.
- The assembly window: how far ahead of a user's read time the loop assembles
  (14.6). Too early serves stale news, too late risks missing the deadline.
- Agent rate limits per user, and whether chat is free or gated (14.8). It is
  the one cost that scales with engagement rather than news volume.
- Whether the writer stage stays on a Sonnet-class model or moves to a
  Haiku-class one (6.5, decision #43 settles caching and batching but not the
  model). This is a quality-versus-cost tradeoff on the one stage that
  produces the product's differentiator, so it is decided by measured eval on
  the `silver.story_clusters` record rather than by estimate. A grounding
  check does not yet exist and is what the eval most needs, because neither
  the readability gate nor schema validation can catch an invented specific.

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
5.1. **M5.1 Trigger hardening:** the external publish trigger (6.11) and the
   timeliness measure (section 8). Ordering constraint: this lands before the
   14-day run below begins. Under GitHub's cron timing every day is late, so
   starting the clock first only means restarting it. M6 is unaffected and can
   proceed in parallel.
6. **M6 Audio + polish:** dialogue script, TTS, podcast feed, remaining
   adapters, OG images, two-week tuning period.
7. **M7 App data layer:** the section 14 schemas and the allocator. Two-score
   and multi-topic scoring (6.4), the story record (14.1), the user model
   (14.2), the allocator plus `tests/test_allocator.py` (14.4), and the
   newsletter record (14.5). Ordering constraint: the 6.4 scoring change lands
   first and additively, so the site path (6.5) keeps publishing untouched
   throughout. Also carries the entitlement model (14.10), not because billing
   belongs in a data milestone but because 14.4 rule 1 reads the plan and the
   allocator cannot be written or tested without it (decision #46). The store
   purchase flow itself belongs to M9 with the client that presents it. M7
   does not gate the v1 definition of done below, which remains a property of
   the site.

8. **M8 App delivery:** read-time scheduling and the assembly loop (14.6),
   and the app API with versioning and account deletion (14.7). Ordering
   constraint: M7's schemas land first, since this milestone serves them.
   Also carries the audio rework that decision #44 requires: single voice,
   per-story clips, lazy rendering, and concatenation for both the site
   episode and the per-user listen. M6 delivered a two-host per-edition
   dialogue and its MILESTONES.md entry is the accurate record of what was
   built then; #44 supersedes the format rather than rewriting that history.
9. **M9 Mobile client:** the Expo app and the EAS release pipeline (14.9),
   including the minimum-supported-version floor from 14.7.
10. **M10 Agent:** the chat and story tracker (14.8), the Story MCP server,
   and the server-side feature flag. Last because it is opt-in, is the only
   component whose cost scales with engagement, and depends on a beta API;
   nothing else in the system may depend on it.

Definition of done for v1: 14 consecutive days of correct, unattended
publication. *Correct* includes on time: a publication that is late under the
section 8 timeliness measure breaks the streak, the same as a missed or
degraded day. Section 8 owns that definition so the two cannot drift. On the
2026-07-21 to 2026-07-27 baseline every day was late, so the streak stands at
zero until M5.1 lands.

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
   change to the site's rendered self-URLs. One config value carries the old
   URL outside the site layer and changes with it: the pipeline `user_agent`
   in config/pipeline.yaml, the contact URL every outbound request advertises.
   Update its URL to the new project site in the same step.
4. Update the mini PC collector's git remote.
4b. Repoint the external publish trigger (6.11). The Worker posts to
   `/repos/{owner}/{repo}/actions/workflows/publish.yml/dispatches` and the
   migration changes both halves of that path, so update the Worker's target
   owner and repo, issue a fresh fine-grained PAT against the new repository
   with `Actions: read and write` (and nothing else), set it with
   `wrangler secret put`, and enable fine-grained PAT access in the new
   organization's settings (an org-level policy, so the repo transfer does not
   carry it). Record the new expiry in SETUP.md. If the Cloudflare account
   itself moved to project ownership, redeploy the Worker there rather than
   editing the old one.
5. Rotate any keys being moved to project ownership; verify spikes 5.1
   and 5.2 from SETUP.md, and `spikes/check_dispatch.py` for the trigger
   credential, still pass with the new credentials.
6. Run one full private publish cycle end to end on the new identity.
7. Flip the repo public, submit the podcast feed to directories, announce.

Exit criterion: one complete unattended 6am publish on the new URL with
healthchecks green, where the `site` run_log row for that day records
`trigger=worker` (6.11) and not `schedule` or `manual`.

The trigger clause is not pedantry. Because either scheduler alone publishes,
a Worker pointed at the old repo returns 404 and a Worker with an unauthorized
token returns 403, and in both cases the cron still publishes, healthchecks
still goes green, and the site still updates. The backup would be dead with
every signal reading normal, and the next step is flipping the repo public. A
publish that only the cron could have produced does not demonstrate the backup
path survived the migration.

## 14. Multi-tenant app layer

**Status.** This section covers the schema and contracts for the per-user app.
The app API surface, the chat and story-tracker agent, read-time scheduling
behavior, and mobile release are specified in a later pass and are not yet
approved for build.

**Scope boundary with section 6.5.** The site edition and the app newsletter
are two consumers of the same stories. Sections 6.1 through 6.4 are shared
verbatim: collection, dedup, clustering, and scoring feed both. Section 6.5
(the site edition) and this section are siblings, not layers. Neither reads
the other's output (decision #37).

### 14.1 Story record

A **story** is a scored cluster whose article text has been written. It is
written once, globally, and reused by every user whose topics match it. No
part of a story is per-reader: the text of a rate-decision story is identical
whether one person or ten thousand open it.

This is the property the whole architecture rests on. Cost tracks how much
news happened, not how many people are reading. Any change that makes story
text depend on the reader breaks it, and should be treated as a design defect
rather than a feature.

```json
{
  "story_id": "string",
  "cluster_id": "string",
  "written_at": "2026-08-04T14:03:00Z",
  "primary_topic": "string",
  "secondary_topics": ["string"],
  "topic_score": 9,
  "general_score": 3,
  "title": "string",
  "summary": "string, one sentence",
  "sources": [ {"name": "string", "url": "string"} ],
  "article": {
    "background": "string, one paragraph",
    "what_happened": "string, one paragraph",
    "why_it_matters": "string, one paragraph",
    "quote": {"text": "string", "attribution": "string",
              "source_url": "string"}
  },
  "audio": {"url": "string", "duration_seconds": 42},
  "model_version": "string",
  "prompt_version": "string",
  "readability_grade": 8.4
}
```

The `article` block is the same shape as the one in 6.5's `edition.json`, and
is produced by the same writer stage under the same grounding and quote rules.
This is deliberate: one writer, one voice standard, one readability gate, two
renderers. A story that fails the gate twice is written without an `article`
block exactly as in 6.5, and remains selectable.

`audio` is nullable and is one clip **per story**, never per user (6.7,
decision #44). A per-user render would reintroduce per-reader cost on the one
stage where it is most expensive. Per-user audio is assembled by concatenating
story clips, which is why each segment is self-contained and why the format is
a single voice: a dialogue flowing across story boundaries cannot be recut.

`audio` is null until a clip has been rendered. Rendering is lazy (6.7), so
absence means not yet requested rather than failed, and the story is always
readable regardless.

`topic_score` and `general_score` carry forward from 6.4 unchanged.

### 14.2 User model

Postgres, never the lake (decision #36).

| Field | Notes |
| --- | --- |
| `user_id` | Present on every user-scoped row from the first migration, including during single-account testing. Adding it later means migrating everything. |
| `auth_provider` | `apple` or `email`. No other value exists in v1 (decision #50). |
| `auth_subject` | The provider's stable identifier: Apple's `sub` claim, or the verified address for email. Unique per provider. |
| `email` | Nullable. Apple's private relay address counts and is stored as given; it is never resolved to a real address. |
| `topic_prefs[]` | **Ordered.** Each entry is `{topic, weight}`. `topic` comes from the closed menu (14.3); `weight` is an integer 1 to 10, default 6. The list order is the user's running order and is the section order in the rendered newsletter. This replaces a flat `topics[]`: the allocator (14.4) needs both the weight and the position. |
| `length` | The newsletter budget, chosen by the user from the presets in 14.4. Stored as the story count, never the preset label. |
| `newsletter_name` | The masthead title, user-editable, defaulting to `Norm's Newsletter`. Display only. It never affects selection, and no pipeline stage reads it. |
| `plan` | The entitlement (14.10). It is an allocator input, not only a billing fact. |
| `read_time_local` | A local wall-clock time, e.g. `06:30`. |
| `timezone` | IANA name, e.g. `America/New_York`. Supplied by the client from the device zone and stored as last reported. It is never inferred server-side from IP, which is wrong for VPN users and unstable for everyone. |
| `seen_story_ids` | Drives the already-seen filter in 14.4. |
| `last_read_at` | When the user last opened a newsletter. Nullable, and null for a user who has never read one. Selects between 14.4's two lookback windows; it is not analytics and is not the feedback telemetry section 11 still calls for. |
| `push_token` | Nullable; push is opt-in. |

**Weight bands are presentation, not data.** The client renders a weight as one
of five labelled bands, but the stored value is the integer. Storing the band
label instead would make the allocator's arithmetic depend on a copy decision
and would collapse ten distinct settings into five.

**`newsletter_name` is not a namespace.** A user has one newsletter. Renaming
it changes a heading, and nothing keyed on `(user_id, local_date)` in 14.5 or
14.6 changes with it.

#### Authentication

**Sign in with Apple and email magic links. No social logins, and no
passwords** (decision #50).

The absence of social login is the deliberate part. Apple Guideline 4.8
requires an app offering any third-party or social login to also offer Sign in
with Apple, so adding one provider is really adding two, plus the account
reconciliation for a user who signs in with Google on Monday and Apple on
Tuesday. Offering neither leaves the app outside the guideline's scope rather
than compliant with it, which is strictly less to build and less to maintain.

Passwords are excluded for the same reason inverted: they look like the cheap
default and are the most expensive credential to own, carrying reset flows, an
email delivery dependency, hashing that must be correct, rate limiting, and
breach exposure. A magic link is a one-time token and has none of that.

- **Apple** is the primary path, since 14.9 ships iOS first. Apple's private
  relay address is accepted as the user's email and never resolved further.
- **Email magic link** covers anyone declining Apple and keeps a later Android
  release from requiring a new identity system.

Sign-in creates exactly one row keyed by `(auth_provider, auth_subject)` and
issues a `user_id`. Everything user-scoped hangs off that `user_id`, which is
why 14.7 resolves identity from the token on every request and never accepts it
as a parameter.

**Reading does not require an account.** An unauthenticated reader can be
served a general newsletter. Signing in is what attaches preferences to a
person, not what unlocks the content, so nothing about this gate contradicts
decision #26's never-an-empty-newsletter guarantee.

**Read time is stored as local time plus IANA timezone, never as UTC.** A
stored UTC hour silently shifts every user's read time by an hour at each
daylight-saving transition. The publish workflow already carries this rule for
one timezone (6.8); here it is per user, so the failure would be silent and
staggered rather than obvious and global.

**"Today's newsletter" is defined per user, not globally.** A user's
newsletter is dated in their own timezone and contains the best stories
available at the moment it was assembled. Two users in different timezones
seeing different content on the same calendar date is correct behavior. There
is no global edition date in the app; 6.5's `date` field is the site's, and
the two must not be conflated.

**There is no edition number in the app either** (decision #53). The site's
sequential "No. 056" counts editions the site published, which is a fact about
the site and not about any reader. The app prototype carries it into the
masthead, the push copy, and the agent's opening line, and each of those is a
claim the app cannot make: two readers opening on the same day did not receive
the same numbered thing. A per-user sequence was considered and rejected as
worse, since it invents an identifier that means nothing to anyone and cannot
be referred to between two readers. The app identifies a newsletter by its
local date, which is true, sufficient, and already in the record.

### 14.3 Topic taxonomy

v1 offers a **fixed, closed menu**. Users select from it; they cannot type
free text. Custom topics are explicitly out of scope for v1 and are a
separate feature layered on later.

The reason is decision #32's failure mode. The scoring call cannot decline a
story: `Topic` is a closed enum, so an unmatched story is not dropped, it is
filed under the nearest wrong topic where it competes under a false label.
With free-text topics that failure gets both more frequent and much harder to
detect, because there is no fixed vocabulary to audit against.

The menu is drawn from the same `Topic` enum as `primary_topic` and
`secondary_topics`, so a user's selection is always directly queryable and no
mapping layer exists to drift.

**The v1 menu is the ten topics already in the enum** (decision #49). No topic
is added, renamed, merged, or retired for the app's first release.

| Topic (enum) | Display name | Editions with a section | Stories |
| --- | --- | ---: | ---: |
| `World` | World | 13 | 43 |
| `Cyber` | Cybersecurity | 12 | 28 |
| `Regulation` | Regulation | 13 | 27 |
| `Business` | Business | 10 | 22 |
| `AI` | Artificial intelligence | 9 | 18 |
| `Science` | Science | 8 | 18 |
| `Tech` | Technology | 8 | 17 |
| `US Politics` | US politics | 6 | 13 |
| `Finance` | Finance | 5 | 10 |
| `Sports` | Sports | 0 | 0 |

Counts are over the first 15 published editions. Display names come from
`SECTION_NAMES` and are already the app's labels, so no new copy is needed.

**`Sports` stays in the menu at zero.** It has never produced a section,
because decision #32 caps routine sport at 3 and the site's editor works from
`general_score`. That is not a reason to remove it; it is the exact case
decision #33 introduced `topic_score` to serve, and it is the cleanest
available test that the two-score change does what it claims. A Sports
subscriber is reachable in the app and was not reachable on the site.

#### Deferred expansion

The app prototype proposes a 20-topic menu. Those additions are recorded here
so the work is not rediscovered, and are **not** part of v1:

- **Add (13):** Climate, Health, Culture, Media, Law and courts, Education,
  Energy, Space, Personal finance, Entertainment, Travel, Food and drink,
  Housing and real estate.
- **Rename:** `US Politics` broadened to Politics.
- **Merge:** `Business` and `Finance` into one Business and markets topic.
- **Retire:** `Regulation` and `Cyber`, both of which are live sections in
  shipped editions and would need their existing rows remapped.
- **Group** the menu under three headings for the picker: the daily spine,
  technology and science, life and culture.

Each addition costs a set of anchored 3, 6, and 9 example stories in
`scoring_v1` (6.4), so an expansion is a rubric re-calibration rather than a
configuration change. Decision #32 is the evidence that those anchors decide
outcomes. The merge and the two retirements additionally touch stored rows in
`silver.story_clusters`, which is why they are a separate, later change rather
than a wider v1.

### 14.4 Allocator (code, no AI)

The allocator decides which stories go into one user's newsletter. It is
deterministic code and replaces the editor for this path only (decision #37).

"The newsletter is a query of the user's topics" is the right shape but
under-specifies the hard part. If each topic surfaces its top 10 and a user
picks 8 topics, they get 80 stories, which is a firehose rather than a
newsletter; a user who picks 1 topic gets 10. Neither is a read. The job the
editor does for the site (a budget, a spread, a lead) still has to happen, and
it has to happen without an AI call per user.

**The user supplies the budget and the spread; the allocator supplies the
selection.** A weight per topic and a chosen length express the reader's own
editorial judgment, which is information the site's editor never had access to
and had to infer. Where that information exists, the allocator uses it rather
than overriding it with global constants (decision #45).

Inputs: the user's ordered `topic_prefs[]` with weights, their `length`, their
`plan`, their `seen_story_ids`, their `last_read_at`, the story table, and the
two lookback windows.
Output: an ordered list of `story_id`s with the claiming topic for each, plus
the lead story.

**Length presets.** The user picks one. The stored value is the count; the
label is client copy and is never stored or matched on.

| Label | Stories |
| --- | --- |
| Front page | 5 |
| Short | 8 |
| As filed (default) | 11 |
| Long | 16 |
| Everything | 20 |

Rules, applied in order:

1. **Apply the entitlement.** Take the first `k` entries of `topic_prefs`,
   where `k` is the plan's topic allowance (14.10). Entries beyond `k` are
   locked: they are not queried and contribute nothing. The gate runs first so
   that no later step can surface a locked topic by any route, including the
   top-up in rule 7.
2. **Query.** Stories whose `primary_topic` **or** `secondary_topics`
   intersects the entitled topics, within the applicable lookback window
   (below), excluding `seen_story_ids`.
3. **Deduplicate across topics.** A story matching two entitled topics appears
   exactly once, claimed by whichever of them comes **earlier in the user's
   order**. That order is already total, so this needs no secondary tie-break.
4. **Compute targets.** `share_i = weight_i / sum(weights)` across entitled
   topics. Multiply each share by `length` and round by **largest remainder**,
   so the targets sum to exactly `length` with no rounding drift. Remainder
   ties resolve by the user's topic order.
5. **Fill.** Each topic takes its target, ranked by `topic_score` descending,
   then `written_at` descending, then `story_id` ascending.
6. **Reclaim and redistribute.** A topic with fewer candidates than its target
   releases the shortfall. Released slots are redistributed across topics that
   still have unselected candidates, in proportion to their weights, by the
   same largest-remainder rule. Repeat until the budget is filled or no
   entitled topic has candidates left.
7. **Top up.** If the budget is still short, fill from stories **outside** the
   user's entitled topics scoring at least `topup_floor` on `general_score`,
   highest first, excluding already-seen and already-selected, and never
   exceeding `topup_max_share` of the budget. These are claimed by their
   `primary_topic` and flagged as topped up. This is normal behavior, not an
   error path.
8. **Lead story** is the highest `general_score` among the selected set.
9. **Order.** Sections follow the user's `topic_prefs` order. Within a section,
   `topic_score` descending, then `written_at` descending, then `story_id`
   ascending. Topped-up stories run after the entitled sections.

**Top-up is bounded on both sides** (decision #56). Rule 7 reads as a single
sentence but decides what the product feels like for the narrowest
subscribers, who are also the likeliest to leave, so its two constants are
specified rather than left to the implementation.

| Constant | Value | Meaning |
| --- | --- | --- |
| `topup_floor` | 6 | Minimum `general_score` for a topped-up story |
| `topup_max_share` | 0.5 | Most of the budget that may come from outside the reader's topics |

**The floor never yields; the budget does.** If stories above `topup_floor`
cannot fill the newsletter, the newsletter is shorter. It is not padded by
lowering the bar. `length` is a maximum the reader chose, not a quota to hit,
and a short good newsletter beats a full weak one. Six is the site's own bar,
so nothing reaches a reader that would not have reached the site.

**The cap exists because a full newsletter is not automatically the reader's
newsletter.** Someone who picks Science and Space, receives four of those and
eleven from Politics and World, has a full newsletter and did not subscribe to
it. At half the budget the top-up is a supplement; past half it is a
substitution. When the cap binds, the shortfall simply stands.

**Topped-up stories are labelled, never silent.** Rule 9 already places them
after the entitled sections; they render as their own closing group. The same
story shown unlabelled under a topic the reader never chose reads as a defect
rather than an offer.

Both constants live in `config/pipeline.yaml` and are tuned against 14.5's
`topped_up` and 14.11's `story_skipped`: if topped-up stories are consistently
skipped, the cap comes down. That is a configuration change, not a redesign,
which is the reason both are constants rather than logic.

**Never an empty newsletter is unaffected.** Decision #26's per-user form
promises a newsletter, not a full one. Rule 7 still always produces something,
and a reader with nothing above the floor in any topic receives a short
newsletter rather than none.

**A topic receiving zero stories is a correct outcome, not a failure.** A
weight of 1 against a total of 40 at `length` 5 rounds to zero, and the band
the client shows for that weight says exactly that: it runs only when the story
is big enough to lead. The reader asked for that behavior.

**There are no per-topic minimum or maximum constants.** A minimum and a
user-set weight are two mechanisms competing for the same job, and the minimum
wins silently, overriding the setting the reader just made. Removing them does
not remove the guarantees they existed for: rule 6 is what stops a quiet topic
from wasting budget, and rule 7 is what stops a quiet user from getting a thin
newsletter.

**Rebalancing for few topics is arithmetic rather than a step.** A
single-topic user has `share = 1.0` and receives their whole `length`. The
earlier "fewer chosen topics means more stories per topic" rule is subsumed.

**Determinism requires every ordering to be total**, so all four tie-break
points are specified rather than left to sort stability: remainder ties (rule
4), score ties (rule 5, resolved by recency then `story_id`), redistribution
order (rule 6), and the claiming topic (rule 3). This is the reason the
allocator is code rather than a prompt, so it is asserted directly in the tests
below.

**Two lookback windows, not one** (decision #48). A single window is asked to
serve two readers who want opposite things. A regular reader opening the app
each morning wants today's news, and a wide window shows them Tuesday's story
on Friday. A reader who has been away, has just signed up, or has just added a
topic wants the backlog, and a narrow window hands them a thin newsletter at
the exact moment they are deciding whether to keep the app. Any single value is
wrong for one of them.

| Window | Applies | Starting value |
| --- | --- | --- |
| `lookback_daily_hours` | The ordinary case | 36 |
| `lookback_catchup_days` | Catch-up, per the triggers below | 7 |

The daily window is deliberately wider than one day. A reader whose read time
drifts, or whose newsletter is assembled after a late collector run, must never
fall into a gap between windows. This is the same reasoning already applied to
`since_window_hours` against the collector's 3-hour cadence: the overlap is
what lets a missed run heal itself instead of leaving a hole.

The catch-up window applies when, and only when, there is a backlog to serve:

- the user has no previous newsletter, which covers a new signup,
- a topic was added since their last newsletter, in which case the wider window
  applies to that topic alone rather than the whole query, or
- `last_read_at` (14.2) is older than the daily window.

Seven days rather than thirty because beyond roughly a week this stops being
catch-up and becomes browsing an archive, which the app already offers as its
own surface.

**Scores do not age, which is why recency is a tie-break rather than an
afterthought.** A story scoring 9 four days ago outranks one scoring 6 this
morning for as long as both are eligible. Without rule 5's `written_at`
ordering, widening any window quietly fills newsletters with older news for
readers whose topics move slowly, and the previous `story_id` tie-break decided
that by an arbitrary string. Recency is the honest tie-break and is equally
deterministic.

**The catch-up window may never exceed the retention period.** Offering seven
days of backlog over five days of retained stories promises what has already
been deleted. Retention is 12 months (14.12, decision #55), so seven days sits
inside it comfortably and this constraint is satisfied rather than pending.
Retention still bounds this value rather than the reverse, so shortening
retention later would require revisiting the catch-up window.

Both windows and the top-up rules live in `config/pipeline.yaml` and land with
the allocator in M7. The budget is no longer a constant there; it is per user.

**Never an empty newsletter.** Decision #26 guarantees the site never has an
unpublished day. The per-user equivalent is harder, because a user with two
niche topics will hit quiet days routinely, and rule 7 is what discharges it.
A user with zero eligible stories still receives a newsletter assembled
entirely from `general_score`.

**Adding a topic backfills immediately.** When a user adds a topic, the last
few days of that topic are available at once, because the stories already
exist and this is only a query. The obvious alternative ("you will start
seeing it tomorrow") puts an empty result at the exact moment a user is
deciding whether the app is worth keeping. This is a direct consequence of
write-once storage and is close to impossible to add under per-user
generation. The same applies to a new signup, whose first newsletter is built
immediately rather than at their first read time.

The catch-up window is what makes both of those deliverable rather than
aspirational. Under the daily window alone, "immediately" would mean whatever
that topic produced today, which for a slow topic is nothing at all.

**Tests (`tests/test_allocator.py`), required before the prompt-free
implementation lands, per CLAUDE.md working rule 4:**

- Total selected equals `length` whenever enough candidates exist, and never
  exceeds it.
- Targets sum to exactly `length` across a range of weight vectors and
  lengths, with no rounding drift.
- Per-topic counts match the largest-remainder targets for a given weight
  vector.
- A single-topic user receives `length` stories.
- A topic weighted far below its peers can receive zero, and the newsletter is
  still full.
- A topic with fewer candidates than its target releases the shortfall, and
  the budget is filled from the remaining topics.
- A story matching two entitled topics appears exactly once, claimed by the
  topic earlier in the user's order.
- Stories in `seen_story_ids` are never returned.
- A free-plan user with more ranked topics than their allowance receives
  stories from exactly the entitled prefix and none from the locked topics,
  including via the top-up path.
- Shares are computed over entitled topics only, so an entitled prefix sums to
  the full `length` rather than the plan silently shortening the newsletter.
- A user whose entitled topics are entirely quiet receives a newsletter via
  `general_score` top-up, capped at `topup_max_share` of the budget.
- No topped-up story scores below `topup_floor`, including when that leaves the
  newsletter short of `length`.
- When too few stories clear `topup_floor`, the newsletter is shorter and the
  floor is not lowered.
- Topped-up stories are flagged, counted in `stats.topped_up`, and ordered
  after every entitled section.
- A user with zero eligible stories in their topics still receives a
  newsletter (the per-user form of decision #26).
- Lead story is the highest `general_score` among the selected set.
- Among stories with equal `topic_score`, the more recently written is selected
  and ordered first.
- A user with a previous newsletter and a recent `last_read_at` sees only
  stories inside the daily window.
- A user with no previous newsletter, and one whose `last_read_at` predates the
  daily window, both draw on the catch-up window.
- A newly added topic draws on the catch-up window while the user's existing
  topics stay on the daily window in the same run.
- Identical inputs produce an identical ordered output, including when weights
  tie, when largest-remainder remainders tie, and when `topic_score` and
  `written_at` both tie.

### 14.5 Newsletter record

The assembled per-user artifact. Distinct from `edition.json`, which remains
the site's published record (decision #17) and is unaffected.

```json
{
  "newsletter_id": "string",
  "user_id": "string",
  "local_date": "2026-08-04",
  "timezone": "America/New_York",
  "assembled_at": "2026-08-04T10:15:00Z",
  "intro": "string | null",
  "lead_story_id": "string",
  "length": 11,
  "plan": "free | pro",
  "stories": [ {"story_id": "string", "claimed_by_topic": "string",
                "topped_up": false} ],
  "allocation": [ {"topic": "string", "weight": 6, "target": 4, "filled": 3} ],
  "stats": {"candidates": 0, "selected": 0, "topped_up": 0, "locked_topics": 0}
}
```

`allocation` snapshots the weights and targets the run actually used. Without
it a newsletter stops being explainable the moment the user re-weights a
topic, and the two questions that will be asked most often, "why did I only
get one Sports story" and "why is this newsletter short", become
unanswerable after the fact. It also makes 14.4's determinism assertion
checkable against a real record rather than only in tests.

`length` and `plan` are recorded per newsletter rather than read back from the
user row for the same reason: both can change between assembly and reading.

The newsletter stores `story_id` references, never copies of story text. A
copy would silently reintroduce per-user storage of shared content and would
let a corrected story go stale in already-assembled newsletters.

`intro` is the one genuinely per-user AI call, because it is about that user's
particular mix. It is cached by a hash of the ordered `story_id` set, so users
who received the same stories share one generated intro. It is nullable: a
failed intro produces a newsletter without one, never a missing newsletter.

`topped_up` records how many stories came from rule 7 rather than the user's
topics, which is the signal for whether their topic selection is too narrow to
sustain a daily read. `locked_topics` counts the ranked topics the plan
withheld, which is the same signal read from the other side and is the honest
measure of how much the free tier is actually costing a given reader.

### 14.6 Read-time scheduling and delivery

An assembly loop runs every 15 minutes. It finds users whose read time falls
within the next window, runs the allocator (14.4) for each, generates the
intro, and writes the newsletter record (14.5). Push fires at the user's read
time, not at assembly.

**Next-occurrence is computed, never stored.** The scheduler resolves
`read_time_local` in the user's `timezone` to the next real instant each time
it runs. Storing a precomputed UTC timestamp reintroduces the drift that 14.2
exists to prevent, one user at a time and silently.

**Daylight-saving edge cases are specified, not left to the library default:**

- **Spring forward.** A read time inside the skipped hour does not exist that
  day. Deliver at the first valid instant after the gap.
- **Fall back.** A read time inside the repeated hour occurs twice. Deliver on
  the first occurrence, never both.

Both are covered by the DST scheduling check that rule 4 already requires.

**Idempotency.** At most one newsletter exists per `(user_id, local_date)`. A
re-run, an overlapping loop, or a retry finds the existing record and does
nothing. This is the same window-plus-idempotency shape as the publish
workflow (6.8), and it is what makes a duplicated or late loop harmless
rather than a double delivery.

**Lateness is not failure.** A late loop assembles and delivers anyway. The
site's timeliness measure (section 8) does not apply here: there is no single
publish time to be late against, and a newsletter that arrives late is worth
more than one that does not arrive. Whether the app gets its own timeliness
measure is an open question (section 11).

**Push is best-effort and never blocks.** A failed or absent push token leaves
the newsletter readable in the app. Push is opt-in.

**Push copy comes from deterministic templates, never from a model** (decision
#52). The templates are filled from fields the newsletter record already holds:
the lead story's title, the story count, and the audio duration when a clip
exists. Nothing is generated.

The reason is 14.1's central property rather than the cost of the call itself.
A per-user generated notification is a second AI call on the per-user path, and
14.1 holds exactly one. Adding a second is the design defect 14.1 names, not a
feature, and it is unusually easy to add by accident because a notification
feels too small to count as a model call. It would also put a model between the
assembled newsletter and the reader's lock screen, where nothing validates the
output and no gate reads it.

Templates additionally make push copy testable, translatable, and identical for
two users who received the same lead story, none of which a generated string
is.

**Observability.** The assembly loop writes one `run_log` row per batch with
counts (users considered, newsletters assembled, skipped as already present,
failed), not one row per user. Per-user rows would add roughly a thousand
rows a day at v1 scale and drown the existing signal. Individual failures are
counted and carry enumerated reason codes, consistent with decision #27.

### 14.7 App API contract

**Versioned from the first public release.** All routes sit under `/v1/`.

**Backward compatibility inside a version is a hard constraint, not a
preference.** Once the app is on the App Store, old clients live in the wild
indefinitely, and a device that never updates will call this API for months.
The site never had this problem because both ends shipped together. Within
`/v1/`, fields may be added and may become nullable; they may not be removed,
renamed, or have their type or meaning changed. A change that cannot be made
additively is `/v2/`.

**Minimum supported version.** Every request carries the client build. A
client below the floor receives a structured upgrade-required response rather
than a broken screen. The floor is configuration, not code, so raising it does
not require a deploy.

**Identity is server-side.** The user is resolved from the request's
authentication token. No route accepts a `user_id` as a client-supplied
parameter. This is the same rule that governs the agent (14.8) and exists for
the same reason: a client-supplied identity is an authorization bypass.

Contract surface, in behavior rather than route shape:

| Capability | Notes |
| --- | --- |
| Sign in | Apple or email magic link only (14.2, decision #50). Exchanges a provider credential for a session token. The only unauthenticated write. |
| Record an event | Accepts the four events in 14.11. Rejected if it names a `user_id`. |
| Fetch today's newsletter | Returns the stored record (14.5). No AI call, no assembly on read. |
| Fetch a story | Serves stored story text (14.1). |
| Read and update topics | A change takes effect on the next assembly; the backfill in 14.4 applies immediately. |
| Read and update read time | Stored per 14.2. |
| Mark stories seen | Feeds the already-seen filter in 14.4. |
| Delete account | Required by Apple Guideline 5.1.1(v). Deletes the Postgres rows; the lake holds no personal data (decision #36), so there is nothing else to erase. |

The API serves stored records. It never generates a newsletter on the read
path, because that would put a per-user AI call behind a user waiting on a
screen and undo 14.1.

### 14.8 Chat and story tracker (Anthropic Managed Agents)

An opt-in agent that answers questions about the user's own stories and tracks
how coverage of a story develops. It is a **side branch**: it is never part of
assembling or delivering a newsletter, and the newsletter path must remain
fully functional with this feature disabled.

**Platform.** Anthropic Managed Agents. Chosen because the tracker needs three
things that would otherwise have to be built: code execution for computing and
charting coverage over time, memory that persists across sessions, and a
server-side scheduler for "tell me when this develops". The runtime charge
(session-hours) is not the deciding factor at v1 scale; those three
capabilities are (decision #40).

**Agent config is created once and versioned.** Sessions reference an agent by
id and pin a version. Creating an agent per request accumulates orphaned
configs and pays creation latency for nothing.

**The Story MCP server is the only data door.** It runs on the app API and
exposes read-only tools: story search, single-story fetch, a coverage
time series, and the user's topics. Every tool is scoped server-side to one
`user_id`.

- The sandbox receives **no database credentials**. All data arrives through
  MCP, already scoped.
- **The client never sends a prompt.** The server builds it from the
  authenticated identity. A client-supplied prompt is prompt injection and
  metered-cost abuse in one.
- Any secret the agent ever needs is held in a Managed Agents vault and
  substituted at egress, never placed in the sandbox. This is rule 5's
  never-write-a-key rule applied to a surface that did not exist when it was
  written.

**Relationship to rule zero (section 2).** Rule zero requires AI calls to emit
schema-validated JSON. The agent's chat output is prose rendered to a human,
so it does not fit that shape, in the same way TTS does not. The rule's intent
is preserved by a hard boundary instead: **agent output is never written into
a story record, a newsletter record, or any table, and is never read by a
later pipeline stage.** It is displayed and discarded. Structured tool calls
the agent makes are validated normally. Any future feature that wants agent
output to become stored data is a new spec question, not an extension of this
one (decision #41).

**v1 chat is ephemeral. There is no saved-conversation history** (decision
#54). A session lives while it is open and is discarded when it closes. The
prototype shows a past-chats list with stored titles and transcripts, and that
is deferred rather than adopted.

This is the direct consequence of #41 rather than a separate restriction. A
past-chats list is a table of agent output, which #41 forbids in as many words.
Deferring the feature keeps #41 true as written, and shipping the feature would
require amending it first. Doing that properly means deciding what a stored
transcript is for, how long it is kept, whether it is covered by decision #36's
single-`DELETE` guarantee, and whether the agent may read its own history back,
which is the point at which unvalidated model output re-enters the data path.
None of that is needed to ship the agent, so none of it is decided here. The whole branch is switchable off from the server without a
client release. Managed Agents is a public beta, and the client shipping it is
an App Store binary that cannot be recalled, so the ability to disable the
feature remotely is a release requirement rather than a convenience.

**Cost isolation.** The agent is metered per session and is the one part of
the system whose cost scales with engagement rather than with news volume. It
is opt-in and rate-limited per user so it cannot compromise the flat-cost
property that 14.1 establishes for everything else.

### 14.9 Mobile client and release

Expo, released through EAS.

**Two release paths, and the difference is the whole point:**

| Path | Contents | Latency |
| --- | --- | --- |
| EAS Update (over the air) | JavaScript and asset changes | Minutes, no review |
| EAS Build plus submission | Anything touching native code | Days, App Store review |

"Production deploys to the App Store" is therefore only half true. Most
changes ship immediately; a minority cannot.

| Environment | Artifact |
| --- | --- |
| int | Internal distribution build, team only |
| qa | TestFlight |
| prod | App Store build, plus over-the-air updates for JavaScript-only changes |

**Released from GitHub Actions**, invoking the Expo CLI, so that one system
answers what shipped and when. `EXPO_TOKEN` is an Actions secret. Rule 5
applies unchanged: never write a key into a file.

**App Store review posture.** Apple scrutinizes news aggregators on
republishing other outlets' content (Guideline 5.2) and on whether an app does
enough to justify existing (Guideline 4.2). The existing rule of paraphrasing
and linking rather than reproducing source text (decision #10) is the correct
posture and is also the honest description of what the writer stage does.
Account deletion (Guideline 5.1.1(v)) is covered by 14.7.

### 14.10 Plans and entitlements

**An entitlement is an allocator input, not a screen.** The free tier is
defined as a cap on how many of the user's ranked topics actually run, which
means 14.4 rule 1 cannot be built without this section settled. This is why
monetization moved out of the release-blocking group in section 11 and into
the group blocking the first line of app code (decision #46).

**Tiers.**

| | Free | Pro |
| --- | --- | --- |
| Topic allowance (`k` in 14.4 rule 1) | The first 3 ranked topics | All ranked topics |
| Length presets | All | All |
| Archive depth | Open question, below | Every newsletter ever delivered |
| Price | none | $9.99 per month, or $100 per year |
| Trial | not applicable | Six weeks, then the chosen term |

The allowance caps **ranked** topics, not chosen ones. A free user still ranks
and weights their whole list; the first three run and the rest are visibly
withheld. Discarding the locked entries instead would destroy the user's
ordering on downgrade and make an upgrade feel like starting over.

**Everything the free tier withholds is a quantity, never the writing.** The
readability gate, the voice standard, and the grounding rules apply identically
on both tiers. Degrading the writing for free users would trade away the one
thing that distinguishes this product from every other aggregator, to protect
a subscription that exists because of it.

**Entitlement is resolved server-side from the authenticated identity**, on
every assembly and every request. The client never supplies its own plan, for
the same reason 14.7 forbids a client-supplied `user_id`: a client-asserted
entitlement is a paywall bypass, and one shipped in an App Store binary cannot
be recalled. The client's copy of the plan drives display only.

**Purchases go through in-app purchase, not a direct payment path** (decision
#47). Apple Guideline 3.1.1 requires IAP for digital content consumed inside
the app, and a subscription to the app's own newsletter is squarely inside it.
The entitlement of record is the server's, derived from the validated store
transaction. A client receipt is evidence, never the source of truth.

**Downgrade is non-destructive.** When Pro lapses, `topic_prefs` is untouched
and the allowance simply narrows. The next assembly runs the first three, and
14.5's `locked_topics` records the rest. Nothing is deleted, so re-subscribing
restores the previous newsletter exactly.

**Assembly never fails on a billing lookup.** An entitlement that cannot be
resolved at assembly time is treated as the user's last known plan, and if
there is none, as free. A newsletter still gets assembled. Decision #26's
per-user form (14.4) does not acquire a payment-system dependency.

**Deferred, and named here so they are not mistaken for settled:**

- **Free-text topics.** The prototype offers "name any topic and the sources
  attach themselves" as a Pro benefit. This is out of scope for v1 on both
  tiers, unchanged from 14.3, and paying for it does not make decision #32's
  failure mode any less real: the scoring call still cannot decline a story,
  so an unmatched one is still filed under the nearest wrong topic. Selling it
  would put the deferred risk on the revenue path.
- **The Sunday retrospective.** "The whole week read across the stories, and
  what to watch next" is a second assembly on a weekly cadence with its own
  record and its own AI call. It is not a variation of 14.4 and needs its own
  specification before it is offered.
Archive depth is settled rather than deferred: retention is 12 months (14.12,
decision #55), so Pro sells a reader's first year. The free tier sees the
current newsletter and a short recent window. The claim is now bounded by a
rule that exists, which is what the earlier deferral was waiting for.

### 14.11 Feedback telemetry

**Instrumented in v1, before its use is decided** (decision #51). This is the
only part of section 14 where deferring the decision destroys the answer.
Every other open question can be settled later at no cost. Behavior that was
not recorded cannot be recovered, so the instrumentation has a deadline that
the analysis does not.

The need arises from personalization itself. With one shared edition, quality
was a single judgment about a single artifact. Per user it becomes "was this
relevant to *this* reader", which is a thousand questions that cannot be
answered by reading a thousand newsletters.

**Events.**

| Event | Fires when | What it answers |
| --- | --- | --- |
| `newsletter_opened` | A newsletter is opened | Whether delivery worked and whether the read time is right |
| `story_opened` | A story is opened from the newsletter | Which topics and score bands earn attention |
| `story_completed` | A story is read to the end | Whether opening it was worth it, as distinct from a headline that merely drew a tap |
| `story_skipped` | A story is scrolled past without being opened | The negative signal, which is the one most often left uninstrumented and the only one that identifies a bad selection |

Each carries `user_id` (server-resolved, never client-supplied), `story_id` or
`newsletter_id`, and a timestamp. Nothing else.

**Most of the instrumentation already exists on the other side.** 14.5 stores
`topped_up`, `locked_topics`, and the `allocation` snapshot on every
newsletter, which is a complete record of what the allocator chose and why.
These four events supply the missing half, so the two can be joined into "what
was selected" against "what was read". Neither half is useful alone.

**Three rules keep this from becoming a liability:**

1. **Events are aggregated, never fed back automatically.** No event adjusts
   any user's weights, topics, or length. The reader sets those, and 14.4
   exists precisely so that selection is explainable rather than emergent.
   Telemetry informs decisions about defaults; it does not become a second,
   invisible allocator.
2. **Behavior only, never content.** An event records that a `story_id` was
   opened. It never records subject matter as free text, which is the point
   at which a behavior log becomes a profile.
3. **This is not `last_read_at`.** That field (14.2) selects between 14.4's two
   lookback windows and does one job. It answers none of the questions above,
   and "reading is already tracked" must not be allowed to close this section.

**Where it lives.** Postgres, keyed by `user_id`, alongside the rest of the
personal data and never in the lake. Account deletion stays one `DELETE`
(decision #36), which is only true if these rows start there.

**What it unblocks.** The free-tier allowance (14.10), the two lookback window
values (14.4), and the top-up constants (14.4) all ship as chosen numbers
rather than derived ones. With these events they become measurable, which is
why the cost of the section, one table and four calls, is out of proportion to
what it settles.

### 14.12 Data retention and deletion

**Retention is about age. Deletion is about a person.** They are separate
mechanisms and neither substitutes for the other. Retention runs on a schedule
and removes old rows for everyone; deletion is immediate, is triggered by one
reader, and ignores every clock below.

**Retention periods** (decision #55):

| Data | Kept | Reason |
| --- | --- | --- |
| Stories (14.1) | 12 months | The longest thing anything else depends on, and what the app's archive is made of |
| Newsletters (14.5) | 12 months | Matched to stories. A newsletter referencing deleted stories is a broken record, so the two clocks cannot diverge |
| `seen_story_ids` (14.2) | 12 months | Tied to stories. A story that no longer exists cannot be shown again, so remembering that it was seen serves nothing |
| Telemetry events (14.11) | 13 months | One month past the others on purpose, so a full year can be compared against the same month a year earlier |

**Twelve months is a product decision, not only a technical one.** It is what
14.10 is able to sell: Pro archive depth is a reader's first year, which is a
specific and keepable claim, unlike "every newsletter ever delivered". A
shorter period would be cheaper and would make that claim false.

The storage cost is small enough not to be the deciding factor. Stories are
text, and 14.5 stores `story_id` references rather than copies (which is
already required for a different reason), so a year of newsletters is a year of
identifiers rather than a year of duplicated articles.

**Retention bounds two features rather than being bounded by them.** 14.4's
`lookback_catchup_days` of 7 and 14.10's archive depth must both sit inside
this window. At 12 months both do comfortably, which is what makes them
honest promises rather than aspirations.

**`seen_story_ids` is bounded by this and by nothing else.** Without a
retention rule it grows for the lifetime of an account and is read on every
assembly, so the most loyal readers would run the slowest queries. Twelve
months holds a daily reader at roughly five thousand identifiers, which stays
a fast indexed lookup indefinitely.

**Account deletion is immediate, complete, and independent of all of the
above.** It removes every row keyed to that `user_id` in Postgres: the user
record, their newsletters, their seen-story history, their telemetry events,
and their push token. It is required in-app by Apple Guideline 5.1.1(v) and is
covered by 14.7's contract surface.

Decision #36 is what keeps this to one operation: personal data never enters
the lake, so there is no append-only history to reconcile and no time-travel
snapshot still holding a deleted reader. That guarantee holds only while every
table holding personal data is known, which is why 14.11's event table is named
here explicitly rather than left to be remembered.

**Stories are not personal data and are never deleted by an account
deletion.** They are global, written once, and shared by every reader (14.1).
Deleting a reader removes the rows that reference stories, never the stories
themselves.
