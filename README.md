# Norm's Newsletter

A fully automated daily news briefing. Software collects news from many free
sources all day, AI groups and rates the stories, and every morning at 6:00 am
US Eastern the system publishes:

1. A **static webpage** (GitHub Pages): the day's headline, an audio player, a
   short numbered "Today at a glance" summary, and 15 to 20 stories that each
   expand into a full plain-English article.
2. A **~10 minute two-host audio brief** (MP3), also served as a podcast feed.
3. A **permanent, browsable archive** of every past edition.

No human touches the daily output. "Norm" is the name of the AI editor persona:
the machine-written text on the site speaks as Norm. The whole thing runs on a
budget of under $25 a month.

> **New to this repo? Read this file, then open [`CLAUDE.md`](CLAUDE.md).** The
> two governing documents are [`SPEC.md`](SPEC.md) (data, schemas, prompts, and
> pipeline behavior) and [`DESIGN.md`](DESIGN.md) (the look of the site and the
> writing voice). Everything the code does traces back to a section in one of
> those two files. This README is a friendly overview, not the source of truth.

---

## The one rule that explains everything: "Rule zero"

> **AI makes judgments. Deterministic (ordinary, predictable) code does
> everything else.**

An AI model is only called in the four places where there is no formula for the
right answer:

1. **Scoring** how newsworthy a story is.
2. **Curating** which stories make the edition (the "editor").
3. **Writing** each story's article text (the "writers").
4. **Writing** the two-host audio script.

Everywhere else is plain Python. AI **never** writes HTML, never touches
storage, and never deploys. And every single thing an AI returns is **JSON that
is validated against a schema in code before anything is allowed to use it.**
If the AI returns something invalid, the code retries once with the error
message included, and if that still fails it falls back to a safe path. A
failure is always contained to the smallest possible scope: one story loses its
article rather than the whole edition breaking.

Once you internalize rule zero, the shape of the whole codebase makes sense: the
Python is the machine, and the AI is four narrow, tightly-fenced judgment calls
inside it.

---

## The mental model: a tiny automated newsroom

| Newsroom role   | In this system                                    |
|-----------------|---------------------------------------------------|
| Reporters       | Source adapters (Python, no AI)                   |
| Copy desk       | Dedup + clustering (code) and scoring (small AI)  |
| Editor-in-chief | Editor agent (curation, one larger AI call)       |
| Staff writers   | Writer stage (one small AI call per story)        |
| Printing press  | Astro static site build + text-to-speech (code)   |
| Librarian       | Archival job (code, no AI)                         |

---

## The end-to-end pipeline

The system runs in two rhythms: a **collection loop all day**, and a **publish
run once each morning.**

```
ALL DAY, every 3 hours (on a small always-on "mini PC"):

  Sources  ->  Adapters  ->  bronze.raw_items  ->  silver jobs  ->  silver.story_clusters
  (RSS/API)   (normalize)   (raw landing table)   (dedup,          (grouped, rated stories)
                                                   cluster, score)

6:00 AM ET, once a day (on GitHub Actions):

  silver.story_clusters
     -> Editor agent (AI): picks and orders stories, writes the glance  \
     -> Writer stage (AI): one article per story, written in parallel    |  edition.json
     -> Readability gate (code): rewrites anything too hard to read     /
     -> Audio build: AI writes a script, then text-to-speech makes an MP3
     -> Astro build: turns edition.json into a static website
     -> Deploy to GitHub Pages
     -> Ping healthchecks.io (a "dead man's switch" that alerts if a run is missed)
     -> Archival job: fold the day into the permanent "gold" record
```

### Step by step

1. **Collect.** Every 3 hours, one Python "adapter" per source fetches recent
   items (Hacker News, RSS feeds, government APIs, and so on) and normalizes
   each one into a standard row. See [`src/adapters/`](src/adapters/).

2. **Enrich.** Feed summaries are usually one thin line. Before storing, the
   collector fetches each article's real page and extracts the main text, so
   later stages have something substantial to work with. See
   [`src/enrich.py`](src/enrich.py).

3. **Land in bronze.** Normalized rows are appended to `bronze.raw_items`, an
   append-only table stored as **Apache Iceberg** files on **Cloudflare R2**
   (object storage). Duplicate items are skipped. See [`src/bronze.py`](src/bronze.py).

4. **Dedup + cluster.** The silver stage reads the day's bronze, removes
   duplicates, then groups items that are about the same real-world story into
   "clusters" using local text-embedding math (free, runs on the machine, no AI
   API). See [`src/silver/`](src/silver/).

5. **Score.** The one AI call in this loop: a small, cheap model rates each new
   cluster 1 to 10 for newsworthiness, assigns a topic, and gives a one-sentence
   reason. Results are stored in `silver.story_clusters`.

6. **Curate (the editor).** Once a day, a larger AI model reads the day's rated
   clusters and produces the "edition core": the headline, the numbered glance
   points, which stories go in which section, and their one-line summaries. See
   [`src/editor/run_editor.py`](src/editor/run_editor.py).

7. **Write the articles (the writers).** For each chosen story, a small AI model
   writes three paragraphs (Background / What happened / Why it matters) using
   only that story's source text plus any prior coverage. These run in parallel.
   See [`src/editor/run_writers.py`](src/editor/run_writers.py).

8. **Assemble + validate.** Deterministic code stitches the editor's curation
   and the writers' articles together with facts the pipeline already owns
   (scores, source URLs, slugs, stats) into a single `edition.json`, then
   validates it against the canonical schema. See [`src/editor/schema.py`](src/editor/schema.py).

9. **Readability gate.** Code measures the reading grade of every generated
   sentence. If the edition reads harder than 9th-grade level, it rewrites the
   hardest parts and re-checks, up to a small budget, then publishes either way
   (and flags it for review if still too hard). See
   [`src/editor/readability.py`](src/editor/readability.py).

10. **Audio.** An AI writes a two-host dialogue script from `edition.json`, then
    Gemini text-to-speech renders it to an MP3. The MP3 is uploaded to R2 (never
    committed to the repo). See [`src/audio/`](src/audio/).

11. **Build + deploy the site.** `edition.json` is committed to
    `site/content/editions/`, and **Astro** builds a static website from all the
    committed editions. It is deployed to GitHub Pages. The site ships with
    almost no JavaScript. See [`site/`](site/).

12. **Archive.** The day's bronze and silver rows are folded into the permanent
    `gold` tables, the day's `edition.json` is stored verbatim, and the daily
    bronze/silver partitions are dropped. Gold is both the permanent record and
    the source the writer stage searches for "prior coverage." See
    [`src/archive.py`](src/archive.py).

Every job writes one row to an `ops.run_log` table so the whole system can be
reviewed weekly.

---

## The technology stack

### Backend pipeline (Python)

- **Python 3.12**, managed with **[uv](https://github.com/astral-sh/uv)** (it
  installs Python, creates the virtual environment, and locks dependencies).
- **[PyIceberg](https://py.iceberg.apache.org/)** to *write* Apache Iceberg
  tables, **[DuckDB](https://duckdb.org/)** to *read* them. No Spark.
- **[pydantic](https://docs.pydantic.dev/)** for every schema and every piece of
  config validation.
- **[sentence-transformers](https://www.sbert.net/)** (model
  `BAAI/bge-small-en-v1.5`) for local text embeddings used in clustering. This
  runs on the machine and costs nothing per run.
- **[httpx](https://www.python-httpx.org/)** for HTTP, **feedparser** for RSS,
  **trafilatura** for article-text extraction.
- **boto3** to upload the daily MP3 to R2's S3-compatible object storage.

### Frontend site (Astro)

- **[Astro](https://astro.build/)** static site generator. It ships **zero
  client JavaScript by default**; the only two scripts on the site are a
  hash-target auto-open for story cards and the native audio player controls.
- Self-hosted fonts (Newsreader, IBM Plex Sans, IBM Plex Mono) via Fontsource.
- **satori + resvg** to generate a per-edition Open Graph share image at build
  time.
- Analytics via **GoatCounter**.

### AI models (all from Anthropic and Google)

| Stage        | Model                                  | Why |
|--------------|----------------------------------------|-----|
| Scoring      | Claude Haiku 4.5 (`claude-haiku-4-5`)  | Cheap, high-volume, prompt-cached |
| Editor       | Claude Sonnet 4.5 (`claude-sonnet-4-5`)| One larger curation call per day |
| Writers      | Claude Haiku 4.5                       | One small call per story, in parallel |
| Simplify     | Claude Haiku 4.5                       | Readability-gate rewrites |
| Audio script | Claude Haiku 4.5                       | Turns the edition into a two-host dialogue |
| Audio voice  | Gemini 2.5 Flash TTS (multi-speaker)   | Two prebuilt voices, behind a swappable interface |
| Embeddings   | `BAAI/bge-small-en-v1.5` (local)       | Clustering, no API, no cost |

Every AI stage validates its output against a pydantic schema, retries once on
failure with the error included, then falls back deterministically.

### Data storage: the "medallion" layout

Everything is stored as **Apache Iceberg** tables on **Cloudflare R2** (via R2's
Iceberg REST catalog). Iceberg gives safe appends, partitioning, and time
travel over files in object storage.

| Layer      | Table                     | What it holds |
|------------|---------------------------|---------------|
| **Bronze** | `bronze.raw_items`        | Raw normalized items, append-only, partitioned by day |
| **Silver** | `silver.story_clusters`   | Deduped, clustered, AI-scored stories, rebuilt per day |
| **Gold**   | `gold.raw_items`, `gold.story_clusters`, `gold.editions` | The permanent record, partitioned by month |
| **Ops**    | `ops.run_log`             | One row per job run, for the weekly review |

The daily MP3 lives in an R2 **object storage bucket** (not Iceberg), and the
`edition.json` publication record is committed into the git repo under
`site/content/editions/`.

### Sources (all free)

Hacker News, Ars Technica, TechCrunch, The Verge, Guardian Technology, OpenAI
blog, arXiv (cs.AI / cs.LG), BBC Business, CNBC, Nature news, Krebs on Security,
The Hacker News, CISA advisories, SEC EDGAR press, Federal Reserve press, and
the Federal Register API. Three keyed sources (NewsAPI, Finnhub, FRED) are
registered but disabled until their API keys are supplied. See
[`config/sources.yaml`](config/sources.yaml).

### Hosting and ops

- **GitHub Pages** hosts the site. **GitHub Actions** runs the daily publish.
- The always-on collector runs on a small "mini PC" via a systemd timer, with a
  disabled GitHub Actions workflow as a backup launcher.
- **healthchecks.io** provides two "dead man's switch" alerts: one for the 6am
  publish, one for the collector cadence. If a job does not check in, it alerts.

---

## Repository map

```
norms-newsletter/
  README.md          <- you are here
  SPEC.md            <- source of truth: data, schemas, prompts, pipeline
  DESIGN.md          <- source of truth: visual system and writing voice
  CLAUDE.md          <- orientation and the seven working rules
  SETUP.md           <- one-time machine setup guide
  MILESTONES.md      <- build log, one entry per milestone

  config/            <- sources.yaml (adapter registry) + pipeline.yaml (thresholds)
  prompts/           <- the four AI prompts + the shared voice standard

  src/               <- the Python pipeline
    adapters/        <- one file per news source
    silver/          <- dedup, clustering, scoring
    editor/          <- the edition: editor + writers + readability gate + schema
    audio/           <- dialogue script + text-to-speech
    config.py        <- the ONLY module that reads env vars / secrets
    collector.py enrich.py bronze.py storage.py runlog.py health.py
    schedule.py archive.py

  site/              <- the Astro static site
    astro.config.mjs <- the ONLY place the site URL + base path are defined
    src/pages/       <- routes
    src/components/  <- one file per DESIGN.md component
    content/editions/<- committed edition.json per day (the publication record)
    fixtures/        <- normal/quiet/fallback sample editions for offline dev

  .github/workflows/ <- publish.yml + collect.yml
  spikes/            <- standalone credential/dependency smoke checks
  tests/             <- pytest suite covering the deterministic layers
  .claude/skills/milestone-verify/ <- the end-of-milestone verification gate
```

Most folders have their own `README.md` explaining what they hold and how they
fit in. Start there when you dive into a subsystem.

---

## How failures are handled

The system is designed to **degrade, never break**. It never silently skips a
day and never shows a broken page.

| Failure                        | What happens |
|--------------------------------|--------------|
| One source/adapter fails       | Log it, skip it, keep going |
| A collector cycle is missed    | The next cycle backfills; bronze dedups the overlap |
| One story's article fails twice| That story publishes as a plain card, no article |
| The editor fails twice         | Publish a "fallback" edition: a ranked top-10 list |
| Almost no data at 6am          | Publish a shorter "quiet" edition |
| Readability still too hard     | Publish anyway, flag it in the run log |
| Text-to-speech fails           | Publish without the audio player |
| The deploy fails               | The missing healthchecks.io ping fires an alert |

There are three **edition types**, and the site renders each differently:
`normal` (the usual full brief), `quiet` (a slow day, fewer stories), and
`fallback` (something went wrong, here is a ranked list with links).

---

## Running it locally

You need Python 3.12 + uv, Node for the site, and credentials in a local `.env`
(see [`SETUP.md`](SETUP.md) for the full one-time setup). Then:

```bash
# Backend pipeline: each stage has a --dry-run that makes no AI calls and
# writes nothing, and a --date to re-run a past day.
uv run python -m src.collector --dry-run          # fetch + normalize, print a summary
uv run python -m src.silver.run_silver --dry-run  # dedup + cluster, print the groups
uv run python -m src.editor.run_edition --dry-run # plan the edition, print it
uv run python -m src.audio.run_audio --dry-run    # write the script, print its length

# The site develops entirely against fixtures, no live pipeline needed:
cd site && npm install && npm run dev

# Tests cover the deterministic layers (adapters, dedup, clustering, schema,
# readability, DST scheduling). They run fully offline.
uv run pytest -q

# The end-of-milestone gate: tests + fixture validation + a hardcoded-URL scan.
uv run python .claude/skills/milestone-verify/verify.py
```

---

## Where to read next

- **[`CLAUDE.md`](CLAUDE.md)** for the seven working rules and the milestone
  workflow.
- **[`SPEC.md`](SPEC.md)** for the exact schemas, prompts, and pipeline
  behavior. The `edition.json` schema in SPEC section 6.5 is canonical.
- **[`DESIGN.md`](DESIGN.md)** for the visual system, the components, and the
  writing voice standard (section 8).
- **[`MILESTONES.md`](MILESTONES.md)** for the build history and the reasoning
  behind decisions made along the way.
```
