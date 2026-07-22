# MILESTONES.md

Build log. One entry per milestone from SPEC.md section 12: what was
built, which spec sections it satisfies, how it was verified, and what was
deferred.

---

## Post-M6: add NPR and PBS NewsHour (World + US Politics beats)

Date: 2026-07-22
Spec: SPEC 6.1 (source adapters, topic_hint vocabulary, v1 sources)
Status: complete, gate green

### The problem

The newsletter wanted more reliable, low-bias sources. Across AllSides,
Ad Fontes, and MBFC, the nonprofit public broadcasters NPR and PBS NewsHour
rate consistently least-biased and are free to ingest via RSS. Two of the
most-neutral outlets overall, AP and Reuters, have no free access (AP is
enterprise-contract only; Reuters killed public RSS in 2020, paid LSEG only),
so they were left out. Separately, the editor's US Politics section (SPEC 6.5
skeleton) had no dedicated source: politics stories only reached it when a
general feed happened to carry one.

### What was built

- `config/sources.yaml`: four new entries on the generic `RSSAdapter`, all
  free/keyless and `enabled: true`, `max_items_per_run: 25`.
  - `npr_world` (feeds.npr.org/1004), `pbs_world`
    (pbs.org/newshour/feeds/rss/world), topic_hint `world`.
  - `npr_politics` (feeds.npr.org/1014, NPR's dedicated Politics feed),
    `pbs_politics` (pbs.org/newshour/feeds/rss/politics), topic_hint
    `politics`. These are the first dedicated feeds for the US Politics beat.
- `SPEC.md` 6.1: added the `topic_hint` vocabulary statement (now nine
  lowercased section-skeleton values, adding `politics` to match the scorer's
  TOPICS and the 6.5 skeleton), documented that the hint is advisory
  provenance only (nothing in silver/scoring reads it; the scorer assigns the
  real topic), and appended NPR/PBS to the v1 sources prose.

No adapter code and no deterministic-layer change: `topic_hint` is a free
string in `SourceConfig`, so `politics` needed no validator edit.

### How it was verified

- `load_sources()` parses all 25 sources; the four new ones load with the
  expected hints, and `politics` hint sources are `[npr_politics,
  pbs_politics]`.
- Live `RSSAdapter.fetch` against both politics feeds returned real items
  (npr_politics 10, pbs_politics 20 over 2 days) with clean dated
  canonical_urls, not redirect shims.
- Feed reachability and grounding measured before adding: all four HTTP 200;
  sample article extraction NPR ~12-15k chars, PBS ~5k, well clear of the
  grounding floor that got the Google News feeds removed.
- `milestone-verify`: 409 passed, fixtures valid, urls derive. Gate green.

### Deferred

- Christian Science Monitor and Deutsche Welle: also clean free low-bias RSS,
  a tier below NPR/PBS in prominence. Candidates for a later breadth pass.

---

## Post-M6: isolate trafilatura extraction (collector segfault)

Date: 2026-07-22
Spec: SPEC 6.10 (configuration: operational knobs in pipeline.yaml)
Status: complete, gate green

### The problem

The `collect` workflow died with exit 139 (SIGSEGV) on 2026-07-22 (run
29925206852). The crash was inside `trafilatura.extract`, a native
library call in `src/enrich.py`, triggered by a `blog.pypi.org` page. A
segfault is not a Python exception, so `enrich.py`'s existing degrade
chain (trafilatura, then the regex fallback, then keep the feed summary)
never got a chance to run: the whole collector process died mid-fetch,
not just the one item.

### What was built

- `src/enrich.py`: the trafilatura call now runs in an isolated `spawn`
  child process (`_trafilatura_extract`, `_extract_worker`,
  `_run_isolated`). A crash now kills only the child, and the parent reads
  that as a failed result and falls back to the regex extractor, same as
  any other trafilatura miss. `spawn`, not `fork`, because `enrich_items`
  calls this from a thread pool and forking a multithreaded parent is
  unsafe; `spawn` also behaves the same on macOS and the Linux Actions
  runner. The parent polls the result queue rather than blocking on one
  `get`, so a dead child falls back immediately instead of waiting out the
  full timeout; only a genuine hang costs the whole budget.
- `src/config.py`: two new `EnrichConfig` knobs, `isolate_extraction`
  (default `true`) and `extract_timeout_seconds` (default `8.0`).
- `config/pipeline.yaml`: the two knobs, documented against the crash, and
  `blog.pypi.org` added to `skip_hosts` as a point fix for the specific
  host (this PR hardens the whole crash class, not just that host).

This is a reliability fix to an existing implementation detail: no
schema, prompt, or pipeline-contract change, and `body_excerpt` semantics
are unchanged. The two config keys are SPEC 6.10-style operational knobs.

### How it was verified

- `milestone-verify` gate: PASSED, 409 tests, fixtures valid, self-URLs
  derive from `astro.config`.
- New tests in `tests/test_enrich.py` exercise the isolation wrapper
  directly with crashing, hanging, and successful stand-in workers (so the
  suite does not depend on trafilatura actually segfaulting), plus a
  wrapper test confirming a crash still yields the regex fallback's text
  rather than a process-killing segfault reaching the caller.
- End-to-end dry run: exit 0, 80 items, 66 of 77 enriched (+65,342 chars),
  no crash.

### Deferred

- A point fix adding `blog.pypi.org` to `enrich.skip_hosts` landed as part
  of this same change; no separate follow-up needed for that host.
- Broader collector reliability (R2 upload timeouts, source no-shows) is
  tracked separately, flagged in the "staff the world beat" entry below.

---

## Post-M6: staff the world beat (three world sources)

Date: 2026-07-22
Spec: SPEC 6.1 (adapter registry), 6.5 (topic vocabulary), 6.6 (briefly)
Status: complete, gate green

### The problem

The 2026-07-21 edition read as hackernews plus bbc, and the bigger stories
of the day (Trump's Canada tariffs, the Space Force launch buy, Novo
Nordisk v. Eli Lilly) landed in `briefly` rather than as cards. Cause was
structural, not a bad day: the enabled roster had zero `world` sources.
`newsapi` (the one world feed) was disabled pending its key, so the world
beat was unstaffed while tech carried five feeds and cyber three. The
editor rule that a section which cannot field two stories collapses into
`briefly` (SPEC 6.6) then guaranteed every world story was orphaned, since
none ever had a sibling to form a section with.

### What was built

- `config/sources.yaml`: added `bbc_world` and `guardian_world`, two
  keyless direct publisher RSS feeds on the same hosts as the already
  proven `bbc_business` and `guardian_technology`, so they ground and
  extract by the same reasoning. No `enrich` denylist entry needed.
- `config/sources.yaml`: flipped `newsapi` to `enabled: true`. Milind
  confirmed `NEWSAPI_KEY` is in Actions secrets as well as `.env`, so the
  unattended collector will not error on it.
- `tests/test_adapters_m6.py`: the "keyed sources ship disabled" invariant
  now asserts only `{finnhub, fred}`; newsapi is enabled once its key is
  provisioned.

World now has three enabled feeds, enough to field a section on its own.

### How it was verified

- `milestone-verify`: GATE PASSED. 409 tests pass, 3 fixtures valid, urls
  derive from astro.config.
- Live smoke fetch of both new feeds: `bbc_world` returned 28 items,
  `guardian_world` 45, both HTTP 200, samples were exactly the world and
  politics stories that had been demoted (Saudi nuclear deal, Trump/Iran,
  Ebola monitoring).

### Deferred

- Collection health: on 07-21 only 7 of 16 enabled sources delivered (32
  items vs 76 the prior day), and MEMORY notes an R2 upload timeout plus a
  SIGSEGV in `collect.yml` on 07-22 that self-healed. That is a collector
  reliability question, separate from source coverage, and worth a look at
  the R2 run logs. Adding feeds does not fix feeds that silently no-show.
- Confirm over the next few editions that world actually forms a two-story
  section and the big stories stop defaulting to briefly.

## Post-M6: the readability gate, and direct publisher feeds

Date: 2026-07-20
Spec: SPEC 6.5 (readability gate), 6.1 (adapter registry), 6.10; decision #14
Status: complete, gate green, live and passing

Two fixes in one pass, both prompted by the first editions that had real
prose in them.

### 1. Readability: 11.9 flagged, now 8.90 passing

**The problem was structural, not stylistic.** Editions published flagged at
grade 11.9 against the grade-9 target (decision #14). Grading each piece of
an edition separately showed why:

| text | grade | revised by the pass? |
|---|---|---|
| story summaries | 17.02 | no |
| glance points | 14.26 | no |
| headline | 12.30 | no |
| articles | 11.53 | yes |

The gate scores every piece of generated text (`readability.edition_text`),
but the revision pass only re-called the writer stage. The editor's own
lines were measured, counted against the average, and then left alone, so
no amount of article rewriting could pull the edition under the limit. The
worst text in the edition was the text nothing could touch.

**What was built.** `src/editor/simplify.py` is the missing half of the
pass. It collects the editor-owned lines that are over the limit, sends
only those to a small model asking for plainer wording of the same facts,
and deterministic code puts the results back by id (`headline`,
`point:<index>`, `summary:<slug>`). The model receives prose and ids and
nothing else, so ordering, topics, slugs and scores cannot move: curation
stays where it was decided (rule zero). Validator before prompt, as
everywhere. Two guards worth naming: a "simplification" that grades harder
than the original is rejected rather than applied, and an AI failure leaves
the original text in place and publishes flagged, like every other failure
in this stage.

**The prompts now carry the arithmetic.** Flesch-Kincaid moves on exactly
two things, words per sentence and syllables per word, so "write simply"
was never going to be actionable. `editor_v1.md` caps summaries at 12 to 18
words and glance points at 20; `writer_v1.md` targets 11 to 13 words a
sentence; both now list the short-word substitutions the gate rewards
("use" not "utilize", "about" not "approximately"). The writer's revision
message states the grade target and the 12-word sentence rule outright
instead of asking for "more simply". These tighten DESIGN section 8's
"average under 20 words" rather than contradicting it, so voice.md is
untouched.

**The pass count is now a budget.** Measured across real editions: one pass
lands about 9.15, two lands between 8.89 and 9.07, which straddles the limit
because each generation differs. `readability_max_passes` (config, default
3) runs the simplify-then-rewrite cycle until the edition passes, and exits
as soon as it does, so an easy day costs one pass.

**Result on live editions:** 12.34 to 8.68 locally, 8.90 on the published
edition, publishing unflagged for the first time. Summaries 17.0 to about
10, articles 11.5 to 8.5.

### 2. Direct publisher feeds replace Google News

The two Google News topic feeds are gone. Their RSS links are opaque JS
shims carrying neither the publisher URL nor the article text, so the
enrichment step could never ground them and every story sourced from them
published as a flat card. They are replaced by The Verge, the Guardian's
technology feed, BBC Business, and CNBC Business, all verified before
registration by fetching a real article from each (2,428 to 5,079
characters extracted).

CNBC rejects the default client string with a 403, so outbound requests now
send one identifying User-Agent, defined once in `adapters/base.py` and
shared by the RSS adapters and the enrichment step. Publishers are entitled
to know who is calling.

Enrichment's hit rate improved as a direct result: 71 of 75 fetched items
improved (+70,462 chars), against 48 of 53 when half the run was Google
News.

### How it was verified

**389 tests passing (13 new, all offline).** New coverage: which lines
`collect_failing` selects and that it orders them hardest first; that
rewrites land in the right places and leave structure, topics, slugs and
scores untouched; unknown ids ignored; a harder "simplification" rejected;
an AI failure keeping the original text; the em-dash ban; and that the
revision loop exits early once the gate passes rather than spending its
budget.

```bash
uv run pytest -q                                          # 389 passed
uv run python .claude/skills/milestone-verify/verify.py   # GATE PASSED
```

**Live:** collector, silver, edition, audio, and a forced publish, all
green. The published page returns 200, the edition grades 8.90, and the
audio is playable.

One test caught a bad assumption of mine rather than a bug: my "harder
rewrite" fixture actually graded *lower* than the original, because
appending a short sentence reduces average words per sentence. The fixture
is now a genuinely denser single sentence, and the arithmetic is documented
in the test.

### Proposed spec amendments (rule 1)

1. **SPEC 6.5**: the readability revision pass covers all generated text,
   not only articles. The editor-owned lines are the ones that graded worst,
   so a pass that cannot reach them cannot meet the target.
2. **SPEC 6.5**: "one automatic revision pass" becomes a configured budget
   (`readability_max_passes`, default 3) that exits early on success. One
   pass provably could not reach grade 9 on real editions.
3. **SPEC 6.1**: one identifying User-Agent on every outbound request.

### Notes

- DESIGN section 8 says "average under 20 words" and also sets the grade-9
  target. On real news vocabulary those two are in tension: 20-word
  sentences grade around 11 to 12. The stage prompts now aim well under 20,
  which satisfies both, but the tension is worth resolving in DESIGN 8 the
  next time it is edited.
- The published headline still grades high (15.4) because it is a single
  sentence and the metric is volatile on one line. It is one line among many
  and barely moves the average, so it is left alone rather than mangled.

---

## Post-M6: article-text enrichment

Date: 2026-07-20
Spec: SPEC 6.1 (body_excerpt), 6.5 stage 2, decisions #10, #16; DESIGN 4
Status: complete, gate green, live

### The problem

The first real edition published 4 expandable stories out of 15. The other
11 were flat cards. The writer stage had skipped them: adapters store the
feed's summary in `body_excerpt`, and feed summaries are one-line blurbs.
Measured on the live `gold.raw_items` partition:

| source | items | empty body | avg chars |
|---|---|---|---|
| hackernews | 58 | 55 | 33 |
| google_news_technology | 24 | 0 | 343 |
| google_news_business | 22 | 0 | 341 |
| the_hacker_news | 4 | 0 | 393 |
| techcrunch | 8 | 0 | 179 |
| arstechnica | 5 | 0 | 73 |

Every source sat at or under the 400-char grounding floor, so decision #16
correctly refused to write articles that would have been padding. This is
the M2 finding ("17 of 19 items have an empty body_excerpt") arriving at the
place where it finally mattered.

### What was built

`src/enrich.py` fetches each item's `canonical_url` and extracts the main
article text (trafilatura, with a paragraph-scrape fallback), filling
`body_excerpt` with what SPEC 6.1 actually describes. It runs in the
collector before the bronze write, so the text is stored once and every
later stage reads it: clustering embeds real text instead of a title,
scoring stops being headline-only (the M2 confidence finding), and the
writer stage has something to ground on.

Safety, all pinned by tests: 10s timeout, capped concurrency, 2MB body cap,
non-HTML content types skipped, and every failure non-fatal so the item
keeps its original summary. `item_id` derives from `canonical_url` and
`published_at`, never the body, so enrichment cannot disturb bronze dedup.
Fetched text is grounding input only, paraphrased and never republished
verbatim (decision #10); the quote policy (#15) is unchanged.

`config/pipeline.yaml` gained an `enrich:` block with `EnrichConfig` in
`src/config.py`. `news.google.com` is in `skip_hosts`: those RSS URLs are
opaque JS shims (~580KB, no publisher URL, no article text), so fetching one
costs a request and returns nothing.

DESIGN 4: StoryCard's flat card now carries a "Read at:" source-link row, so
a story the writer could not ground still reaches its origin. Milind's call.

### Results, measured

```
collector --dry-run:  fetched 53 of 110 items, improved 48 (+49,248 chars)
                      75 items at or above the 400-char floor (was near zero)
edition --dry-run:    17 groundable, 3 collapsed (was 4 and 11)
local edition:        11 of 11 stories with articles
live edition:         13 of 13 expand, 0 flat cards
```

Verified live: page 200 with 13 "Read the full story" cards and no flat
cards, audio 200 (4.3MB), feed enclosure correct. Spot-checked an article
against its source: plain English, grounded, no invented specifics.

### Verification

375 tests passing (22 new, all offline: fetching goes through
`httpx.MockTransport`). Coverage: extraction from an HTML fixture including
script and style removal, the paragraph fallback, the skip rules (already
rich, skip_hosts, disabled), every failure mode returning empty (error
status, non-HTML, oversized, timeout, connection error), truncation to the
SPEC 6.1 length, `item_id` stability, order preservation, and that a weaker
extraction never replaces a better feed summary.

```bash
uv run pytest -q                                          # 375 passed
uv run python .claude/skills/milestone-verify/verify.py   # GATE PASSED
```

### Known limitation

Google News items (about half of each run) stay unenrichable and keep their
~340-char blurb. Making them groundable means replacing those two feeds with
direct publisher RSS, which is a `config/sources.yaml` change and no code.

### Proposed spec additions (rule 1)

1. **SPEC 6.1**: `body_excerpt` may be filled by fetching the item's
   `canonical_url`; the `enrich` config, the `skip_hosts` escape hatch, and
   the rule that any fetch failure falls back to the feed summary.
2. **DESIGN 4 (StoryCard)**: the null-article card carries source links.
3. Note in SPEC 6.1 that Google News RSS links are not enrichable.

### Still open

The readability gate remains over the limit (grade 11.9 after the revision
pass, against the grade-9 target), so editions publish flagged. That is
SPEC 6.5's publish-and-flag path working as designed, but it is the next
thing worth tuning now that there is real prose to measure.

---

## M6 Audio + polish

Date: 2026-07-20
Spec: SPEC 12.6, 6.7, 6.1, 6.5, section 7, section 8; DESIGN.md section 10;
decisions #2, #4
Status: offline-complete, gate green, live pipeline proven end to end except
the R2 audio upload and the public deploy. Both are held on external
prerequisites (see "Held").

Scope for this milestone was the full M6 line: audio, all remaining SPEC 6.1
sources, satori OG images, real podcast enclosures, and the tuning window,
with the live bring-up attempted.

### What was built

**The audio build (SPEC 6.7, decision #4).** Validator first, per rule
zero: `src/audio/schema.py` defines the two-host `DialogueScript` (ordered
turns, both speakers required, em-dash ban) and is the authority on a valid
script; the word band (1,300 to 1,600) is a config value checked by the
caller, not baked into the schema. `prompts/audio_script_v1.md` (voice.md
prepended like every stage) drives one small Haiku-class call in
`src/audio/script.py`, which validates the reply and retries once on an
off-band length, then accepts a structurally valid script rather than losing
the audio. `src/audio/tts.py` is a swappable `Synthesizer` interface with a
`GeminiSynthesizer` multi-speaker backend (decision #4); it maps the two
speakers onto the two configured prebuilt voices, computes the duration
exactly from the PCM sample count, and encodes to MP3 with `lameenc` (no
system ffmpeg needed). `src/storage.py` gained `upload_audio`, which puts the
MP3 to R2 over the S3 API (distinct from the catalog token) at
`/audio/YYYY-MM-DD.mp3` and returns its public URL. `src/audio/run_audio.py`
ties it together: read the committed edition, write the script, synthesize,
upload, and inject `{url, duration_seconds, size_bytes}` back into
edition.json. Every failure is contained to "publish without an audio row"
(SPEC 7): a fallback edition, a script that fails twice, a TTS failure, or an
upload failure all leave `audio` null and never block the deploy. Wired into
`publish.yml` step 6, replacing the M5 no-op, before the commit so the
published edition carries the block.

**All remaining SPEC 6.1 sources.** One generic config-driven
`adapters.rss.RSSAdapter` serves every plain-RSS feed (TechCrunch, an AI-lab
blog, two Google News topics, Nature, Krebs, The Hacker News, SEC EDGAR,
Federal Reserve press), with the feed URL in the registry rather than in
code. Bespoke adapters cover the APIs: `arxiv`, `federal_register`, `cisa`
(keyless, enabled) and `newsapi`, `finnhub`, `fred` (keyed, registered
disabled until their credential is present so unattended runs stay clean).
All produce rows through `build_item`, so the dedup-critical derivations
stay in one place, and all fail per item rather than per feed. The collector
now passes each source's `name` and optional `feed_url` to its adapter;
`SourceConfig` gained the optional `feed_url`. 17 sources registered, 14
enabled.

**Per-edition OG images and the launch assets (DESIGN.md section 10).**
`site/src/lib/og.ts` renders a 1200x630 PNG per edition with satori and
resvg at build time (paper field, wordmark, double rule, date, headline),
fonts read from the self-hosted Newsreader/Plex packages; a build-time
endpoint `og/[date].png.ts` prerenders one per edition and the edition pages
point `og:image`/`twitter:image` at it through the config-derived URL
(non-edition pages keep the static SVG). The same pipeline renders the
3000x3000 ledger podcast artwork (`podcast-artwork.png`), which the feed's
`itunes:image` now references (directories reject SVG). The methodology
page's pipeline SVG is authored inline and accessible. No client JavaScript
is added; the build still emits zero JS bundles.

**Real podcast enclosures.** `audio.size_bytes` was added to the edition
schema (`editor/schema.py`) and the Astro Zod schema (`content.config.ts`);
`feed.xml.ts` now emits a real enclosure `length` from it and an
`itunes:owner` with the decision #21 contact email.

**A live-surfaced schema fix.** The first live audio call returned a 400:
the Anthropic structured-output format rejects array `minItems` above 1.
The editor and writer response schemas carried the same constraints and
would have failed the first live editor call identically (M3's live test was
dry-run only, so it never hit this). `_api_schema` in `editor/schema.py` now
strips the value-constraint keywords the API subset does not support
(minItems/maxItems, string lengths, numeric bounds, pattern, format); the
pydantic models still enforce every one of them on the parsed reply, so
nothing is weakened (rule zero). `audio/schema.py` reuses that one helper.

**Config and deps.** An `audio:` block in `pipeline.yaml` and `AudioConfig`
in `config.py` (script model, TTS model, the two voices, word band); R2
object-storage settings in `Settings` (endpoint, access key, secret, bucket,
public base) and the three data keys already present. New deps: `boto3`,
`lameenc` (Python); `satori`, `@resvg/resvg-js` (site). SETUP.md documents
the five new R2 audio secrets.

### How it was verified

**Tests: 345 passing (50 new), all offline.** Anthropic and Gemini are both
stubbed at the client boundary, `lameenc` encodes a real buffer, and the
adapters parse recorded fixtures. New coverage: the script schema against
each malformed shape and the word-count band; generate_script's in-band,
retry-to-band, accept-off-band, and fail-twice paths; PCM duration exactness,
MP3 encoding, and the Gemini backend with a fake client (including the
missing-key and empty-audio errors); build_audio's happy path and every
contained failure (fallback, dry-run, TTS, upload, script); audio-block
injection keeping the edition valid; the generic RSS adapter and each bespoke
adapter (normalization, since filter, cap, malformed skip, missing-key
error); and that the committed registry loads and every enabled adapter
resolves and constructs.

```bash
uv run pytest -q                                          # 345 passed
uv run python .claude/skills/milestone-verify/verify.py   # gate: all PASS
cd site && npm install && npm run build                   # 12 pages, 3 OG PNGs + 3000x3000 artwork, 0 JS
```

**Live, against the real APIs and R2 (read + audio stages proven):**

```bash
uv run python -m src.editor.run_edition --dry-run                 # reads real silver, no AI
uv run python -m src.audio.run_audio --dry-run --date 2026-07-19  # real script call: 41 turns generated
# direct Gemini TTS check: real 141 KB MP3, 96 kbps 24 kHz mono, 12s, measured exactly
```

The script call is what surfaced and confirmed the `minItems` fix. The TTS
check rendered a real MP3 to a temp file (not R2, not committed), proving the
Gemini multi-speaker call, the lameenc encode, and the duration/size
measurement all work live.

### The live R2 upload (done)

Milind provisioned the R2 audio credentials and the bucket `norms-audio` was
created over the S3 API. The full storage and linking path then ran live:
Gemini TTS rendered the dialogue, `upload_audio` put the MP3 to R2 at
`audio/2026-07-19.mp3` (286,560 bytes, `audio/mpeg`, 24s, confirmed present
with `head_object`), the audio block was injected into the committed
edition, and the site build carries it in both places:

```
page:  <audio src=".../audio/2026-07-19.mp3">   "Listen to today's brief"
feed:  <enclosure url=".../audio/2026-07-19.mp3" length="286560" type="audio/mpeg" />
       <itunes:duration>24</itunes:duration>
```

Two notes on that run, both honest limitations rather than code defects:

- **The dialogue text was hand-written, not model-written.** The Anthropic
  account ran out of credits mid-milestone, so the script stage 400'd. The
  script stage itself is proven live from the earlier dry run (a real 41-turn
  dialogue). The upload proof used a short hand-built script through the same
  validator so the storage path could be exercised. Re-run
  `uv run python -m src.audio.run_audio --date <date>` once credits are
  topped up for a fully model-written episode.
- **The bucket's public URL does not serve yet.** The object is in R2, but
  `R2_AUDIO_PUBLIC_BASE` returns 404 because r2.dev public access is not
  enabled on the newly created bucket. That is a Cloudflare dashboard toggle
  (R2, the bucket, Settings, Public access), not something the S3 API can
  set. The pipeline, the page, and the feed all already point at the right
  URL; it starts resolving the moment public access is on.

### The full unattended publish (done)

Milind cleared decision #22 and authorized the publish. Pages was already
enabled but in legacy branch mode, which `actions/deploy-pages` cannot use;
it was switched to `build_type: workflow`. The five R2 audio secrets were
added to Actions (15 total). M6 was committed and pushed, then
`gh workflow run publish.yml -f force=true` ran the whole SPEC 6.8 sequence
green:

```
gate -> Build edition -> Audio build -> Commit edition -> Astro build
     -> configure/upload/deploy-pages -> Ping healthchecks -> Archive to gold
```

Run 29761969723, conclusion success. The live site and feed both return 200.
CI produced edition No. 43, a **normal** edition with a fully model-written
audio block: `duration_seconds: 297`, `size_bytes: 3561408`, uploaded to
`audio/2026-07-20.mp3` and confirmed present in R2. So the complete chain
(editor, writers, readability gate, dialogue script, Gemini TTS, R2 upload,
commit, deploy, healthchecks, archival) is proven end to end in CI, not just
locally. The published feed carries real enclosures for both editions.

**One item remains, and it is a Cloudflare dashboard toggle.** The R2 objects
exist but `R2_AUDIO_PUBLIC_BASE` still returns 404, because r2.dev public
access is not enabled on the `norms-audio` bucket. The S3 API cannot set it
(R2, the bucket, Settings, Public access). Every link already points at the
right URL and starts resolving the moment that is switched on. Until then the
page and feed reference an MP3 a listener cannot yet fetch.

### Decisions and notes

- Module placements beyond SPEC section 5's names: `src/audio/schema.py`,
  `script.py`, `tts.py`, `run_audio.py` (matching SPEC 5's `audio/script.py`
  and `audio/tts.py`); `adapters/rss.py` and the six bespoke adapter files.
- TTS model pinned to `gemini-2.5-flash-preview-tts` (a newer
  `gemini-3.1-flash-tts-preview` is now visible and can be swapped in config).
- The word band came in low on the seeded fixture edition (a small hand-built
  edition); a full real day will run longer. The accept-off-band behavior is
  intended and the band is a tuning-window value.

### Proposed spec additions (rule 1)

1. SPEC 6.1: the generic RSS adapter and the `feed_url` registry key.
2. SPEC 6.7 / 6.10: `R2_AUDIO_PUBLIC_BASE` and the `audio.url` derivation
   (rule 6 governs the site's own URLs; the enclosure is R2-hosted per SPEC
   6.7); the `audio:` config block.
3. SPEC 6.5 / 6.7: `audio.size_bytes` for the RSS enclosure length.
4. SPEC 2 / 6.5: the API-schema subset rule (structured output does not
   accept value constraints, so they live only in the validator). This is a
   rule-zero clarification, and the fix means the first live editor call will
   now succeed where it would previously have 400'd.

### Deferred

- **The two-week tuning window** (decision #2): `cluster_threshold`, the
  scoring rubric, and the audio word band observed on live multi-source data.
  This overlaps the 14-day definition of done and runs once sources and the
  public deploy are live.
- **Keyed sources** (NewsAPI, Finnhub, FRED) stay disabled until their keys
  are set; flip `enabled: true` per source.
- **The live MP3 upload and the public publish**, held as above.

---

## M5 Automation

Date: 2026-07-20
Spec: SPEC 12.5, 6.8, 6.9, section 8, section 7; decisions #5, #7, #17
Status: offline-complete, gate green. The live public publish is held
pending decision #22 (see "Held for approval").

### What was built

**The DST scheduling gate (SPEC 6.8, decision #7).** `src/schedule.py`,
one pure function `is_publish_time(now_utc)`, true only when it is 06:00 US
Eastern local time on `now`'s Eastern date. The two crons fire at 10:00 and
11:00 UTC and exactly one of them is 6am Eastern on any date: 10:00 UTC in
EDT, 11:00 UTC in EST. The gate is code, not YAML, so the DST behavior is
the same thing the tests pin. `zoneinfo`, no third-party tz, no clock but
the one passed in.

**The gold record and archival job (SPEC 6.9).** `src/archive.py` defines
the three-table `gold` namespace ratified in planning: `gold.raw_items`
(bronze's schema), `gold.story_clusters` (silver's schema), and
`gold.editions` (one row per edition, the edition.json verbatim plus
edition_number and edition_type as columns), all partitioned by month.
`archive_day` reads today's bronze and silver partitions, folds them into
gold, stores the day's edition verbatim, expires snapshots older than the
configured window, and drops the daily partitions. "Compacted Parquet"
(SPEC 6.9) is concrete: each day is folded into its month partition with a
single overwrite of the whole month, so a month is one data file rather
than one per day, and that same overwrite is what makes the job idempotent
(keyed by item_id / cluster_id / date, so a re-run merges the same keys to
the same rows). The partition drop is last, so a failure earlier leaves
bronze and silver intact for a re-run, and is skipped when the partition is
already empty so an idempotent re-run is a clean no-op. Month partitioning
needs PyIceberg's Rust transform bindings, so `pyiceberg-core` was added.

**Prior-mention retrieval (SPEC 6.5 stage 2).** `retrieve_prior_mentions`
in `src/editor/context.py`, empty since M3, now queries gold. The match
cannot key on cluster_id (it is `sha256(seed_item_id)`, so the same story
reported on a later day gets a different id), so it is semantic: the story's
headline and summary are embedded and cosine-matched against recently
published clusters in gold, reusing the M2 embedding model and
`cluster_threshold` over the configured lookback. Only clusters that
actually appeared in an edition count as prior coverage. The catalog is
threaded through the writer stage (`run_writers`, `write_one`) as an
optional argument; with no catalog it returns empty, which is both the M3
behavior and what keeps the offline writer-stage tests offline.

**Healthchecks pings (SPEC section 8).** `src/health.py`: `ping(url,
signal)` for the start / success / fail signals, a no-op when the URL is
unset and one that never raises, because a monitoring blip must not fail an
edition that built fine. Wired into the collector's cadence check; the
publish check is a workflow step so it fires from the deploy's success even
if the Python job crashes.

**The two workflows (SPEC 6.8, decisions #5, #17).**
`.github/workflows/publish.yml`: a `gate` job that calls
`src.schedule.is_publish_time` and lets exactly one of the two daily crons
through (or `workflow_dispatch` with `force: true`), then a `publish` job
running SPEC 6.8 steps 2 to 10: build the edition, the M6 audio no-op,
commit the edition.json publication record and push (decision #17), `npm ci`
+ Astro build, Pages deploy via configure/upload/deploy-pages, the
healthchecks success ping (reached only on a good deploy, so a failed deploy
is a missing ping per SPEC 7), and the archival job.
`.github/workflows/collect_fallback.yml`: the disabled Actions backup
collector (decision #5), manual by default with the 3-hour cron commented,
running the collector then chaining silver after it (the collector -> silver
chaining deferred from M2).

**Config (SPEC 6.10).** An `archive:` block in `config/pipeline.yaml` and
`ArchiveConfig` in `src/config.py`: `prior_mention_lookback_days` (30) and
`snapshot_expiry_days` (7). Keys added by the milestone that needs them.

### How it was verified

**Tests: 295 passing (23 new), all offline.** No credentials, no network, no
model load. New coverage: the DST gate at the EDT and EST hours, both DST
transition days, the day before spring-forward, an off-the-hour manual
trigger, and the naive-datetime rejection; the archival job folding a day
into gold and dropping both daily partitions (verified with a fresh table
reload, not a stale write handle), idempotent re-run, month compaction to a
single data file, snapshot expiry collapsing to the protected current
snapshot, dry-run writing nothing, and a missing edition reported but still
archiving the data; prior-mention retrieval matching a published follow-up,
excluding a scored-but-unpublished cluster, excluding an unrelated story and
one outside the lookback window, and returning empty with no catalog; the
healthcheck ping's no-op, signal suffixes, and error-swallowing.

```bash
uv run pytest -q                                          # 295 passed
uv run python .claude/skills/milestone-verify/verify.py   # gate: all PASS
```

**Workflows lint clean.** `actionlint .github/workflows/*.yml` passes.

**Archival read path against live R2**, read-only and free:

```bash
uv run python -m src.archive --dry-run --date 2026-07-20
# bronze rows: 19, silver clusters: 19, edition.json: present
```

The gate reads the real M2 partition and the on-disk edition without
writing or dropping anything, exercising the whole read side of the job.

### Held for approval (the live publish)

The milestone's remaining step, one full unattended publish that deploys to
Pages, was not run. Two reasons, both requiring Milind's decision:

1. **Decision #22** says the site stays unpublished until OBA/BD
   preclearance, and a GitHub Pages deploy on the personal Free account is a
   public site. Triggering the publish workflow now would publish the site
   before that gate. I will not do that unilaterally.
2. It makes a paid Anthropic editor call and pushes a commit to the repo,
   and the request in this session was to stop at offline verification.

When Milind is ready and OBA/BD status allows it, the live bring-up is:

```bash
# 1. commit and push M5 (workflows must be on GitHub to run)
# 2. enable Pages: repo Settings -> Pages -> Source: GitHub Actions
#    (or: gh api -X POST repos/OWNER/REPO/pages -f build_type=workflow)
# 3. confirm the six Actions secrets are set (SETUP.md 3.4)
# 4. trigger a forced run and watch it:
gh workflow run publish.yml -f force=true
gh run watch
```

### Decisions and notes

- Module placements beyond SPEC section 5's names: `src/schedule.py`,
  `src/health.py`. `src/archive.py` is named in the repo map.
- Dependency added: `pyiceberg-core` (Rust transform bindings), required for
  the month-partition writes SPEC 6.9 specifies.
- Healthchecks success ping is placed after the deploy rather than as a
  literal numbered step, so a failed deploy is a missing ping (the SPEC 7
  dead man's switch) and there is never a contradictory success-then-fail
  pair. Archival runs after it, with its own run_log row.
- The publish workflow commits the generated edition.json and pushes to the
  default branch. That is decision #17 (the committed editions are the
  publication record), performed by CI, distinct from the CLAUDE.md rule
  about me committing on request.

### Deferred

- **Methodology "running totals from gold"** stays on M4's honest interim:
  totals derived from the committed editions. Reading gold at Astro build
  time would require R2 credentials during the site build and break the
  rule-4 principle that the site builds without the live pipeline, so gold
  totals are deliberately not wired into the static build.
- **GoatCounter analytics** remains out (M4 had pencilled it for M5).
  DESIGN section 7 allows only two client scripts; a third analytics script
  is a DESIGN change, so it waits on Milind's ruling (no-JS pixel vs a
  sanctioned deferred script). SETUP 2.6 shows the account exists.
- **Audio build** (SPEC 6.8 step 6) is an M6 no-op placeholder in the
  workflow.
- The **pre-launch migration** (SPEC 13) and the public launch itself are
  post-M6, gated by decisions #20 and #22.

### Open questions raised for the spec

The gold layout, the prior-mention match (semantic, over published clusters,
within a config lookback, returning `{date, summary}`), and the concrete
readings of "compacted Parquet" (per-month single-file rewrite) and "expire
snapshots older than 7 days" (on the gold tables the job touches) were
undefined in SPEC 6.9 and are implemented as ratified with Milind in
planning. They want writing into SPEC 6.9. The one live-behavior question
that blocks the definition of done is whether a public Pages deploy is
permitted before OBA/BD clearance (decision #22), or whether M5's DoD is the
verified machinery with the public deploy held until the launch gate.

---

## M4 Site

Date: 2026-07-20
Spec: SPEC 12.4, 6.6; DESIGN.md sections 1-9; edition schema SPEC 6.5
Status: complete, gate green

### What was built

**The URL rule, first (SPEC 6.6, CLAUDE.md rule 6).** `site/astro.config.mjs`
is the single place `site` and `base` are defined
(`https://aryanzodge123.github.io`, `/norms-newsletter`), with
`trailingSlash: always` and directory output so the DESIGN section 7 routes
resolve on Pages. Every self URL on the site derives from these two values
through `site/src/lib/urls.ts` (`href` for root-relative, `abs` for absolute
via `Astro.site`, `editionPath` for permalinks). The pre-launch migration
(SPEC 13) changes only these two config values. The milestone-verify `urls`
check moves from SKIP to PASS: no hardcoded self URL in `site/src`, and every
self URL in `site/dist` starts with the configured prefix. External source
links (arstechnica.invalid, news.ycombinator.invalid) pass through untouched.

**The data seam (SPEC 6.6).** `site/src/content.config.ts` defines an Astro
content collection over `content/editions/*.json` with a Zod schema that
mirrors the canonical edition schema (SPEC 6.5): the discriminated union of
normal / quiet / fallback shapes, `strict()` throughout, so a malformed edition
fails the build rather than rendering broken HTML. It is the front-end analogue
of `src/editor/schema.py`. `site/src/lib/editions.ts` holds the pure query and
formatting helpers (`latestEdition`, `neighbours`, `topicsWithEditions`,
read-time and duration formatting). Per the decision confirmed with Milind,
`content/editions/` is the build's data source and M4 seeds it by copying the
three fixtures to dated files (`2026-07-19/20/21.json`); M5 commits the real
editions into the same directory. `site/fixtures/` stays the canonical
hand-built dev input and the gate keeps validating it.

**Tokens and type (DESIGN 3).** `site/src/styles/tokens.css` carries every
color, family, rule, and spacing value as CSS custom properties, light-only.
`global.css` self-hosts the three families via Fontsource, latin subset,
`font-display: swap`, weights 400/500 only. Total woff2 payload is 143KB,
inside the 300KB budget.

**Components (DESIGN 4).** One Astro file per named component: Masthead,
Footer, AudioRow, GlanceBlock, SectionLabel, StoryCard, PullQuote, Sidebar,
StatTiles, BrieflyStrip, PrevNextBar, NoticeBanner, RankedList, ArchiveRow,
plus `EditionView` (the DESIGN 5 template switch) and `PageShell` (the frame
for non-edition pages). StoryCard is a styled `details/summary` with the
disclosure marker suppressed, `id={slug}` for deep-linking, and the DESIGN
null-`article` branch: a plain div with no chevron and no expand affordance.

**Templates (DESIGN 5).** `EditionView` renders the normal / quiet / fallback
compositions. Verified against the seeded fixtures in `dist`: the normal
edition (07-19) renders 6 expandable cards, 1 flat null-article card, 2
pull quotes, the glance, the audio row, and the sidebar; the quiet edition
(07-20) renders the 3-point glance with the `norm` point and the "Sections
held" sidebar row and sentence; the fallback edition (07-21) renders only the
NoticeBanner and RankedList, with no glance, audio, or sidebar.

**Pages and feed (DESIGN 7).** `/` (latest), `/YYYY/MM/DD/` permalinks (shared
`EditionView` so they are identical to `/`), `/archive/` (month-grouped rows,
year and topic filter links, edition count), prebuilt `/archive/{topic}/` per
section name, `/about/`, `/methodology/`, `/subscribe/`, and `/feed.xml`. The
feed is an RSS 2.0 + iTunes endpoint with all links via `abs()`; a per-episode
audio enclosure renders only when `audio` is non-null (the normal fixture
carries one; the others do not). Every page is semantic HTML with one h1.

**The two scripts, and only those (DESIGN 7, 9).** The StoryCard script
(hash-target auto-open plus the Collapse control) lives inline in BaseLayout;
the native audio reveal-on-play lives inline in AudioRow. The build emits zero
JS bundles. The site works fully with JavaScript disabled: native
details/summary expands, and a `<noscript>` reveals the audio element.

### How it was verified

**Build is clean.** `cd site && npm run build` Zod-validates all three seeded
editions and emits 13 routes. Zero JS bundles, two CSS files, 143KB of fonts.

**Gate green.** `uv run python .claude/skills/milestone-verify/verify.py`:
tests 272 passed (M1-M3 suite untouched), fixtures 3 valid, urls PASS (all
self URLs derive from the configured prefix). The urls check is the M4 goal
and is now active.

**Lighthouse, real Chrome headless against `npm run preview`:**

| page | performance | accessibility |
|------|-------------|---------------|
| `/` (fallback) | 100 | 100 |
| `/2026/07/19/` (normal) | 99 | 100 |
| `/2026/07/20/` (quiet) | 100 | 100 |
| `/archive/` | 100 | 100 |

All above the DESIGN section 9 floor of 95.

**Em-dash ban (rule 7).** No em dash in `site/src` or the built HTML.

Concrete commands for Milind:

```bash
cd site && npm install && npm run build          # 13 routes, clean
npm run preview                                   # browse http://localhost:4321/norms-newsletter/
uv run python .claude/skills/milestone-verify/verify.py   # gate: all PASS
```

### Decisions and notes

- `/` renders the newest edition, which in the seed set is the fallback
  (2026-07-21). This is correct "latest" behavior, not a defect; the normal
  and quiet templates are viewable at their permalinks.
- Component and lib placements beyond DESIGN 4's named components:
  `EditionView` and `PageShell` (composition seams), `lib/urls.ts`,
  `lib/editions.ts`, `content.config.ts`. DESIGN 4 names the leaf components;
  these are the plumbing that assembles them.
- Static OG image is `public/og-default.svg` (ledger style), referenced via a
  config-derived URL. The satori per-edition OG image is M6 (DESIGN 10).
- The Collapse control is handled by the StoryCard script (it is a StoryCard
  interaction, the script DESIGN 7 allots to StoryCard). With JS off it
  degrades to a scroll-up anchor; native summary click still collapses.

### Deferred

- Binary and generated assets: podcast artwork PNG (3000x3000), satori
  per-edition OG images, final favicon set, methodology pipeline SVG. M6
  (DESIGN 10). A static OG fallback and the existing favicon ship now.
- Real `content/editions/` commits, the Pages deploy, and prev/next over real
  publication history: M5 (SPEC 6.8). M4 seeds the fixtures as stand-ins.
- Audio player population and real podcast enclosures: M6 (SPEC 6.7). `audio`
  is null on quiet/fallback; the feed and AudioRow both handle null. The one
  non-null fixture audio proves the enclosure and player paths render.
- Methodology "running totals from gold": populated when gold exists (M5).
  Until then the page derives honest totals from the committed editions.
- GoatCounter analytics tag: wired in M5 with the deploy.

### Open question raised for the spec

`key_points[].topic` and `briefly[].topic` in the fixtures use short tags
("Tech", "Cyber") while SectionLabels use full names ("Artificial
intelligence"). DESIGN 4 requires full names only for SectionLabel; M4 renders
the glance and briefly topic tags verbatim as supplied by the pipeline. If a
tag-to-full-name mapping is wanted for display consistency, it belongs in
DESIGN 4 as an explicit rule.

---

## M3 Edition

Date: 2026-07-20
Spec: SPEC 12.3, 6.5, section 7, section 8, decisions #3, #8, #12, #13,
#14, #15, #16, #17
Status: complete, gate green

### What was built

**The schema, first (SPEC 6.5).** `src/editor/schema.py`, written before
either prompt per rule zero, and the module the milestone-verify gate
already imports. It exposes `validate_edition(obj)` (raises `EditionInvalid`)
and `EDITION_SCHEMA` (a JSON Schema dict), so the gate works either way. It
encodes the constraints SPEC 6.5 states in prose but not in its JSON block,
each with the sentence it comes from: 4-6 key_points normal / exactly 3
quiet, the `norm` key_point quiet-only and at most one, 2-4 stories per
section, a 20-story ceiling, skeleton section names in skeleton order,
nullable `audio`, nullable `article` per story, optional `quote`, unique
slugs and cluster_ids, briefly that cannot repeat a section story, and the
reduced fallback shape (date, edition_number, edition_type, notice, ranked
top 10). A fallback edition dispatches to a separate, smaller model because
it is a genuinely different shape, not a normal edition with fields left
out. Two derived sub-schemas, `EDITOR_RESPONSE_SCHEMA` and
`WRITER_RESPONSE_SCHEMA`, are what the two AI calls are constrained to, so
the prompts and the validator cannot drift. `extra="forbid"` throughout,
matching `score.py` and `config.py`.

**Reading the day (SPEC 6.5).** `src/editor/context.py` joins today's
silver rows back to today's bronze partition on `member_ids`, because
silver stores source names and member ids but no URLs and no member text,
and edition.json needs `sources: [{name, url}]`, briefly links, and
excerpts to ground on. Both partitions are still present at this point;
SPEC 6.9 drops them only after deploy. It drops null-scored clusters (SPEC
6.4c) and computes each cluster's grounding characters, the number the
writer gate tests. `retrieve_prior_mentions` is defined and returns empty
until gold exists in M5.

**Structural decisions in code (SPEC 6.5, rule zero).**
`src/editor/plan.py` picks the edition type from configured thresholds
before any AI call (`choose_edition_type`), derives `edition_number` from
the editions on disk (decision #17, re-running a date reuses its number),
derives collision-safe slugs (`unique_slugs`), applies the min-2 section
rule and the 3-dead-sections shrink rule (`plan_sections`), and counts the
`stats` block. The editor agent is told which mode it is writing, never
asked to choose one.

**Stage 1, editor agent (SPEC 6.5).** `src/editor/run_editor.py` and
`prompts/editor_v1.md`. One Sonnet-class call, voice.md prepended by the
same pattern as `run_silver.py`. Returns the edition core; slugs, scores,
source URLs, stats and edition_number are all filled in afterward by code,
so the model is never asked for a fact the pipeline owns. Invalid twice is
the one edition-sized failure and produces a fallback (SPEC section 7).

**Stage 2, writer stage (SPEC 6.5).** `src/editor/run_writers.py` and
`prompts/writer_v1.md`. One small call per story over a thread pool. The
grounding gate runs first in code: below `min_grounding_chars` no call is
made and the story publishes with `article: null` (decision #16). Invalid
twice also yields `article: null`. The quote policy (decision #15) is
lint-enforced after validation: a quote over length, without attribution,
or whose `source_url` is not one of the story's own sources is stripped and
the rest of the article kept.

**Readability gate (SPEC 6.5, decision #14).** `src/editor/readability.py`
implements Flesch-Kincaid directly rather than pulling a dependency, so the
syllable heuristic is pinned by tests and cannot shift under a version
bump. Edition average must be grade <= 9. Over the line, the runner's one
revision pass re-calls only the stories that are themselves over grade,
with their hardest sentences listed, then re-grades; still over, it
publishes and sets `readability_flag` in the run log. Quotes are measured
but never rewritten (a real person's words).

**Assembly and runner.** `src/editor/assemble.py` is the deterministic seam
that joins editor output, writer results, and the code-owned facts into a
validated edition, and builds the fallback edition. `src/editor/llm.py`
holds the call-validate-retry-fallback shape shared by both stages, mirror
of `score.py`. `src/editor/run_edition.py` is the entry point:
`--dry-run`, `--date`, one `ops.run_log` row in a `finally` block carrying
`readability_flag` and `ai_cost_estimate_usd`. It writes edition.json to
`site/content/editions/`; committing it is M5's job (SPEC 6.8 step 7).

**Fixtures (DESIGN.md 5).** `site/fixtures/normal.json`, `quiet.json`,
`fallback.json`, hand-built to be representative rather than captured,
because M4 develops against them and today's real data yields an edition
with every article null. `normal.json` deliberately carries one collapsed
card and two quotes so M4 builds both StoryCard branches from day one.

**Config (SPEC 6.10).** An `editor:` block in `config/pipeline.yaml` and
`EditorConfig` in `src/config.py`: the two model ids, retry count, writer
concurrency, the quiet/fallback cluster thresholds, and
`min_grounding_chars`. Keys added by the milestone that needs them, per
spec.

### How it was verified

**Tests: 272 passing (96 new), all offline.** Anthropic is stubbed at the
client boundary (`tests/test_writer_stage.py` defines the fake and
`test_run_edition.py` reuses it), and Iceberg writes go to the local
sqlite catalog. No key, no network, no model load.

```bash
uv run pytest -q
```

Coverage: every SPEC 6.5 constraint asserted by rejection; all three
fixtures validate; the em-dash ban; edition-type selection at each
threshold boundary and that null scores do not count; slug determinism,
truncation, collisions, and date re-run; the grounding gate making zero
calls below the floor and one at it; writer failure containment with call
counts; quote lint stripping without losing the article; Flesch-Kincaid
against a hand-computed value, the grade-9 boundary, the hardest-first
sentence report, and the quote exclusion; the revision pass fixing an
edition and flagging one that stays hard; the fallback path from an
editor that fails twice and from a thin day that never calls the model.

**Live dry run against R2**, read-only and free:

```bash
uv run python -m src.editor.run_edition --dry-run
```

Reads the real 19-cluster partition M2 wrote, decides a normal edition (19
>= 12), plans Technology / Business / Science / Cybersecurity as available
with AI and US politics held to briefly, and marks every story collapsed.
That last part is expected: the grounding gate is working, and M2's finding
that Hacker News items reach silver with an empty body_excerpt means every
current cluster is below the 400-character floor. The read path,
edition-type decision, section plan, and grounding gate all exercise end to
end without an AI call.

**Gate:** `uv run python .claude/skills/milestone-verify/verify.py` passes.
The fixtures check goes from SKIP to PASS in this milestone; urls stays SKIP
until M4 creates `site/astro.config.mjs`.

### Findings that affect later milestones

**On today's sources the writer stage produces almost nothing.** Every one
of the 19 clusters is below the grounding floor, so a live full run would
publish a valid normal edition in which every story is a collapsed card,
and the run would be `partial` for that reason. This is the correct read of
the input, not a defect: it is the M2 empty-body finding surfacing exactly
where predicted. M6's RSS sources carry summaries and close most of it. The
edition path is honest on real data today rather than hallucinating over
missing text.

**The live full run was left for Milind to invoke.** It makes one
Sonnet-class editor call (writers are all gated off by the grounding floor
above) and costs real money, so it is not run automatically. The command:

```bash
uv run python -m src.editor.run_edition            # writes site/content/editions/2026-07-20.json
uv run python -m src.editor.run_edition --date 2026-07-20   # re-run reuses edition No.
```

### Decisions and notes

- Module placements not named in SPEC section 5: `editor/schema.py` and
  `editor/readability.py` are named there; added `editor/context.py`,
  `editor/plan.py`, `editor/assemble.py`, `editor/llm.py`, and
  `editor/run_edition.py` (matching SPEC 5's `editor/run_editor.py` /
  `run_writers.py`).
- Full section names live in code (`SECTION_NAMES`), because DESIGN.md
  SectionLabel requires "Artificial intelligence", not "AI", and SPEC 6.5's
  own example uses the full name as the `name` value. The editor is given
  full names and never invents one.
- Editor and writer models pinned to dated ids
  (`claude-sonnet-4-5-20250929`, `claude-haiku-4-5-20251001`) for the same
  eval-stability reason M2 pinned the scorer.
- Two test expectations were wrong, not the code: "area" is two vowel
  groups ("a" + "ea") under the heuristic, and "spent" is a word. Both are
  now the documented, pinned behavior.

### Deferred

- Committing edition.json to the repo and the Pages deploy: M5 (SPEC 6.8).
- `audio` block population: M6 (SPEC 6.7); it is written as null and the
  schema allows it.
- Prior-mention retrieval body: M5, when gold exists. The interface is in
  place and tested empty.
- Astro rendering of the fixtures and the urls gate check: M4.

### Open questions raised for the spec

Six points were undefined in SPEC 6.5 and are implemented as proposed under
the goal directive, all as deterministic code and none as AI output. They
want explicit ratification into SPEC 6.5:

1. **`edition_number`** derives from the count of committed editions
   (decision #17); a re-run of a date reuses its number.
2. **`slug`** is the lowercased title, non-alphanumerics to hyphens,
   truncated at 60 chars on a word boundary, `-N` on collision within an
   edition.
3. **`stats`** all five fields are counted from the partitions and the
   assembled edition, never generated.
4. **Grounding floor** `min_grounding_chars` (proposed 400): below it no
   writer call is made and the story publishes without an article. This is
   the code home for decision #16 on today's thin sources.
5. **Quiet and fallback thresholds** `min_clusters_for_normal` (12) and
   `min_clusters_for_quiet` (3) quantify SPEC 6.5's "broadly quiet day"
   and section 7's "zero/near-zero data". A day below the quiet floor
   produces a fallback edition, which is also the abbreviated-day shape,
   not only the failure shape.
6. **Fallback notice** text is deterministic (SPEC section 7 / DESIGN.md
   NoticeBanner), because a fallback is often triggered by an AI failure
   and its notice cannot itself depend on an AI call.

Confirmed with Milind before the build: a story below the grounding floor
publishes with `article: null` rather than being written from a headline
alone, and the edition type is chosen by deterministic code from configured
thresholds rather than by the editor agent.

---

## M2 Silver

Date: 2026-07-20
Spec: SPEC 12.2, 6.4, decisions #2 and #6, SPEC 7, section 8
Status: complete, gate green

### What was built

**Dedup (SPEC 6.4a).** `src/silver/dedup.py` collapses duplicate item_ids,
then same-day canonical_urls, keeping the earliest published. Bronze
already rejects duplicate item_ids, so the canonical_url pass is the one
that earns its keep: SPEC 6.1 permits `shortener_hosts` to change mid-day
and calls the resulting double-write an acceptable duplicate. This is
where that duplicate is absorbed before it can become two clusters.

**Clustering (SPEC 6.4b).** `src/silver/cluster.py` embeds locally with
`BAAI/bge-small-en-v1.5` and does a greedy pass in published_at order,
joining the best cluster at cosine >= `cluster_threshold` and always
merging identical canonical_urls. The math takes embeddings as an
argument rather than computing them, so tests drive it with hand-built
vectors and never load a model.

**Scoring (SPEC 6.4c).** `src/silver/score.py`. Validator before prompt,
per rule zero: `ScoreResponse` is the authority on a valid score, and the
API is separately asked to constrain output to the same schema as a belt
to the validator's braces. On a validation failure the call retries once
with the error text included, then returns `score=None`. Failure is
contained to one cluster.

**Prompts.** `prompts/voice.md` (DESIGN.md section 8 verbatim) and
`prompts/scoring_v1.md`, an anchored rubric with 3/6/9 examples in each of
the nine SPEC 6.5 sections, three worked examples at length, topic
tiebreakers, and confidence guidance.

**Table (SPEC 6.4).** `src/silver/table.py` defines
`silver.story_clusters` partitioned by ingest_date. Unlike bronze it is
rebuilt rather than appended: each run re-clusters the whole day and
overwrites the partition.

**Runner.** `src/silver/run_silver.py` reads today's bronze, dedups,
embeds, clusters, carries forward unchanged scores, scores the rest,
overwrites the partition, and writes one `ops.run_log` row in a `finally`
block. `--dry-run` clusters and prints without AI calls or writes;
`--date` re-runs a past day.

### How it was verified

**Tests: 167 passing (91 new), all offline.** Anthropic is stubbed at the
client boundary, embeddings are hand-built vectors, and Iceberg writes go
to a local sqlite catalog, so the suite needs no credentials and loads no
model.

```bash
uv run pytest -q
```

Coverage: dedup collapse rules and ordering; clustering threshold
behavior including the `>=` boundary, best-cluster selection among two
candidates, centroid drift, canonical_url override, and cluster_id
stability across rebuilds and growth; the scoring validator against every
malformed reply shape; the retry-then-null path and its call counts; cost
arithmetic; partition overwrite semantics; carry-forward.

**Threshold calibrated against real embeddings** before spending AI calls:

| pair | cosine |
|------|--------|
| Two paraphrases of the same Fed story | 0.839 |
| Two paraphrases of the same Apple story | 0.915 |
| Two unrelated stories | 0.364 |
| Closest pair in the live 19-item bronze partition | 0.662 |

0.82 separates same-story from different-story on this data. The Fed pair
clears it by only 0.019, which is the number to watch during the decision
#2 observation window.

**Live run against R2**, three commands:

```bash
uv run python -m src.silver.run_silver --dry-run   # 19 items -> 19 clusters, nothing written
uv run python -m src.silver.run_silver             # scored 19, 0 null, est $0.0206
uv run python -m src.silver.run_silver             # scored 0, 19 carried forward, $0.0000
```

The third command is the M2 idempotency proof: zero requests to
api.anthropic.com, and the run_log row records `ai_cost_estimate_usd` of
exactly 0.0.

**Prompt caching confirmed engaged.** The system prompt is 4484 tokens
against Haiku 4.5's 4096-token minimum cacheable prefix. Below that floor
the API accepts `cache_control` and silently declines to cache, so
`ensure_cacheable()` counts tokens at startup and warns rather than
trusting it, and a test asserts the rubric stays above the floor. The
effect is visible in the bill: 19 calls cost $0.0206 against roughly
$0.085 uncached.

**Stored state read back** (DuckDB over a PyIceberg scan):

```bash
uv run python -c "
import duckdb
from src.storage import get_catalog
from src.silver import table
clusters = table.ensure_table(get_catalog()).scan().to_arrow()
con = duckdb.connect()
print(con.execute('SELECT topic, count(*), avg(score) FROM clusters GROUP BY topic').fetchall())
print(con.execute('SELECT headline, member_count, score FROM clusters ORDER BY score DESC NULLS LAST LIMIT 10').fetchall())
"
```

19 rows, all cluster_ids distinct, no null scores, average confidence
0.611.

**Gate:** `uv run python .claude/skills/milestone-verify/verify.py` passes
with tests green and fixtures and urls correctly skipped until M3 and M4.

### Findings that affect later milestones

**17 of 19 bronze items have an empty `body_excerpt`.** The Hacker News
API returns `text` only for Ask HN posts and comments, never for link
submissions, so most items reach silver as a headline and nothing else.
Consequences: `embed_chars` is inert for those items and clustering runs
on titles alone, and scoring is headline-only, which shows up as an
average confidence of 0.611 and visibly conservative scores. This is an
M1 adapter limitation surfaced by M2, not an M2 defect, and fixing it is
outside this milestone's scope. It matters most for M3, where the writer
stage grounds articles on cluster excerpts (SPEC 6.5) and would have
nothing to ground on. M6's RSS sources carry summaries and largely close
the gap; whether the HN adapter should additionally fetch linked article
text is a spec question for Milind, not a decision I should make.

**The score distribution is honest but narrow: 17 of 19 landed at 1 to 4.**
That is the correct read of this input rather than a broken rubric. The
partition is 18 Hacker News items and 1 RSS item, and the HN top page that
day held a 2014 blog post, an "Ask HN" thread, a nostalgia piece about
digital cameras, and a game-streaming tool. Those genuinely are 1s and 2s
for a general-audience daily brief. The single 7 (India's first private
orbital launch) was the most newsworthy item present. The rubric cannot
be judged until there are sources that carry general news, which is M6.
Two items look under-scored to me on inspection, both plausibly mid-range
stories flattened by the missing body text above.

### Decisions and notes

- Module placements not named in SPEC section 5: `silver/table.py` and
  `silver/run_silver.py` (named to match SPEC 5's `editor/run_editor.py`).
- Dependencies added: `numpy` (imported directly, previously only
  transitive).
- `bronze.read_partition` added so silver can read a day without a
  watermark. Re-reading the whole day is what makes a missed cycle heal
  itself on the next run.
- Scoring pins the dated model id `claude-haiku-4-5-20251001` rather than
  the `claude-haiku-4-5` alias. SPEC 6.4 calls this table the future eval
  dataset, and an eval set whose `model_version` silently changes under it
  is not an eval set.
- Two tests initially failed on float32 precision rather than on logic. A
  vector built to sit exactly on 0.82 lands a fraction under it after
  normalization, so the `>=` boundary is now tested at cosine 1.0 with
  identical vectors, where the dot product is exact.

### Deferred

- `gold.history` and the archival job: M5, per SPEC 12.
- Prior-mention retrieval for the writer stage: M3, needs gold.
- Tuning `cluster_threshold` on real data: the two-week window in decision
  #2, during M6.
- Running silver automatically after each collector cycle: M5. It is
  invoked by hand in M2.

### Open questions raised for the spec

Five points in SPEC 6.4 were undefined and needed a decision before code
could exist. Three were settled with Milind before the build: the
embedding model (SPEC 11's open question, now `BAAI/bge-small-en-v1.5`),
partition-rebuild write semantics, and constraining the scoring `topic` to
the SPEC 6.5 section vocabulary. All three belong in SPEC 6.4.

Two were implemented as proposed under the goal directive and still want
explicit ratification:

1. **Embedded text.** Title plus the first `embed_chars` (500) characters
   of body_excerpt. Title alone is too sparse to separate near-duplicate
   wire copy; the full 1200-char excerpt lets boilerplate dominate.
2. **`headline` and `summary_seed` derivation.** SPEC 6.4 lists both as
   columns without saying where they come from. Rule zero forbids AI prose
   and the scoring JSON contains no headline, so both are deterministic:
   the seed member's title verbatim, and its body_excerpt truncated to 500
   characters.

Also worth writing into SPEC 6.4: `cluster_id` is
`sha256(seed_item_id)[:32]` where the seed is the earliest-published
member. The partition rebuild needs stable ids to recognize clusters it
has already scored. The known edge case is that an item arriving late but
published earlier displaces the seed, which reads as a new cluster and
costs one extra scoring call. Documented and pinned by a test rather than
engineered around.

---

## M1 Skeleton

Date: 2026-07-19
Spec: SPEC 12.1, 6.1, 6.2, 6.3, 6.10, section 8
Status: complete, gate green

### What was built

**Configuration (SPEC 6.10).** `src/config.py` loads `config/sources.yaml`
and `config/pipeline.yaml` plus `.env`, validates everything with pydantic
models that reject unknown keys, and is the only module in the codebase
that reads environment variables. R2 credentials are required;
later-milestone keys are optional so an M1 run does not demand an M6 key.

**Normalization primitives (SPEC 6.1).** `src/adapters/base.py` holds the
`RawItem` model, the `Adapter` protocol, `clean_url`, `canonicalize`,
`make_item_id`, and `build_item`. Adapters call `build_item` rather than
constructing rows directly, so the dedup-critical derivations happen in
one place. `make_item_id` pins the published_at string form to
`%Y-%m-%dT%H:%M:%SZ` in UTC, so an adapter's choice of tzinfo cannot
change an item_id.

**Adapters (SPEC 6.1).** `hackernews.py` (Firebase API, no key) and
`arstechnica.py` (RSS). Both cap at `max_items_per_run`, filter on
`since`, and skip malformed entries rather than failing the feed.

**Storage (SPEC 6.3, section 8).** `src/storage.py` owns the R2 Data
Catalog connection. `src/bronze.py` defines `bronze.raw_items`,
partitioned by `ingest_date`, with an append that deduplicates both within
the batch and against stored partitions. `src/runlog.py` defines
`ops.run_log` per the section 8 table, partitioned by `run_date`, with
`make_run_id` producing the SPEC 6.1 format.

**Collector (SPEC 6.2).** `src/collector.py` resolves adapters from the
registry, runs each inside its own try/except, writes bronze, and records
one run_log row. A failing adapter makes the run `partial`, never
`failed`. The run_log write sits in a `finally` block so a failed bronze
write still leaves a record.

### How it was verified

**Tests: 76 passing, all offline.** Hacker News runs through
`httpx.MockTransport`, Ars Technica parses fixture text, and Iceberg
writes go to a local sqlite catalog, so the suite needs no credentials.

```bash
uv run pytest -q
```

Coverage by layer: canonical_url cleanup rules including idempotency and
the shortener fallback path; item_id determinism across timezone
representations; adapter normalization, `since` filtering, item caps, and
malformed-entry handling; config validation failures; bronze idempotency
and cross-partition dedup; run_log row shape and status validation;
collector adapter isolation.

**Live run against R2**, three commands in sequence:

```bash
uv run python -m src.collector --dry-run   # fetches, prints, writes nothing
uv run python -m src.collector             # wrote 19 rows, skipped 0
uv run python -m src.collector             # wrote 0 rows, skipped 19
```

The third command is the idempotency proof required by SPEC 6.2.

**Stored state confirmed by reading it back** (DuckDB over a PyIceberg
scan):

```bash
uv run python -c "
import duckdb
from src.storage import get_catalog
from src import bronze, runlog
items = bronze.ensure_table(get_catalog()).scan().to_arrow()
runs = runlog.ensure_table(get_catalog()).scan().to_arrow()
con = duckdb.connect()
print(con.execute('SELECT source, count(*), count(DISTINCT item_id) FROM items GROUP BY source').fetchall())
print(con.execute('SELECT run_id, job, status, items_in, items_out FROM runs ORDER BY started_at').fetchall())
"
```

Result: 19 bronze rows (18 hackernews, 1 arstechnica), every item_id and
canonical_url distinct. Two run_log rows, the second showing
`items_in=19, items_out=0`, which is idempotency visible in the
observability table rather than only in a log line.

**Gate:** `uv run python .claude/skills/milestone-verify/verify.py` passes
with tests green and fixtures and urls correctly skipped until M3 and M4.

### Decisions and notes

- `src/` is a Python package, so registry paths written in the SPEC 6.1
  form (`adapters.hackernews.HackerNewsAdapter`) resolve under it. The
  yaml stays verbatim per the spec.
- Module placements not named in SPEC section 5: `adapters/base.py`,
  `storage.py`, `bronze.py`.
- Dependencies added: `pyyaml`, `pyiceberg[sql-sqlite]` (local catalog for
  tests), and `pytest` in a dev group.
- Two bugs the tests caught during the build. The redirect resolver was
  being tested with a handler that failed on the second hop, and the HN
  fixture encoded escaped entities where the real API sends actual tags,
  which masked the strip-then-unescape ordering in `strip_html`.
- Observed: the HN adapter walks the full ranked topstories list
  sequentially, roughly 500 requests and about 30 seconds per run, because
  the list is ranked by score rather than time and cannot be short
  circuited on `since`. Correct and free, but a candidate for
  parallelization during the M6 tuning window.

### Deferred

- systemd timer and the disabled Actions backup launcher (SPEC 6.2
  runtime): not in the M1 scope line, lands with M5 automation.
- healthchecks.io ping for collector cadence: M5.
- The remaining v1 sources in SPEC 6.1: M6.

### Open question raised for the spec

`make_item_id` needs a fixed string form for published_at or the hash is
not reproducible. SPEC 6.1 gives the formula but not that encoding. It is
pinned in code and covered by tests. Worth writing into SPEC 6.1 as an
explicit clause, since it belongs to the frozen rules.
