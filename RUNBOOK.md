# RUNBOOK.md - Norm's Newsletter operations guide

This is the "how to run the project" guide for whoever is in charge of keeping
Norm's Newsletter alive. It tells you how to check that everything is working,
what to look at when something breaks, and how to fix it.

It is written for a junior engineer. You do not need to have built the project to
follow it. If a command is shown, you can run it.

**What this guide is not:** it is not the first-time setup guide. Setting up a
fresh machine (installing Python, uv, Node, and creating the accounts) is
[`SETUP.md`](SETUP.md). This runbook assumes the system is already deployed and
running: the collector is on the mini PC, the tables are on Cloudflare R2, the
site is on GitHub Pages, and monitoring is live.

**The two documents that own the truth** are [`SPEC.md`](SPEC.md) (data, schemas,
pipeline behavior) and [`DESIGN.md`](DESIGN.md) (the look of the site and the
writing voice). When this runbook says "SPEC 6.5" it means that section number.
If SPEC and DESIGN ever disagree, **stop and ask the owner (Milind). Do not pick
one yourself.**

---

## 1. Your most useful command

Almost every check in this runbook starts with one read-only command. Run it from
the repo root:

```bash
uv run python scripts/norm.py status
```

It prints a health snapshot: the latest published edition, the most recent run of
each job and how long ago it was, a warning if the collector has gone quiet, and
any job runs that did not fully succeed. It only reads. It never changes anything
and never costs money. Get comfortable with it first; the rest of this guide
leans on it.

Other read-only views from the same tool:

```bash
uv run python scripts/norm.py runlog --days 3        # recent job runs, newest first
uv run python scripts/norm.py runlog --job collector # just the collector's runs
uv run python scripts/norm.py table silver --date 2026-07-20
uv run python scripts/norm.py cost --days 7          # AI spend per day vs. budget
```

See [`scripts/README.md`](scripts/README.md) for the full list.

---

## 2. The 60-second mental model

Norm's Newsletter is a tiny automated newsroom. Two things run on a schedule:

1. **The collector, every 3 hours, on the mini PC.** It fetches news from many
   free sources, cleans it up, and stores it. Right after collecting it runs the
   "silver" step, which groups items into stories and rates them with a small AI.

2. **The publish run, once a day at 6:00 am US Eastern, on GitHub Actions.** It
   takes the day's rated stories, has AI curate and write the edition, checks the
   reading level, builds the audio, builds the website, deploys it, and files the
   day away into the permanent record.

Two ideas explain almost all of the behavior you will see:

- **Rule zero: AI only makes judgments; ordinary code does everything else.** AI
  is called in exactly four places (scoring, editing, writing, audio script), and
  every AI answer is checked against a strict format before it is used. If the
  check fails, the code retries once, then falls back to a safe path.

- **Degrade, never break.** The system is built to publish *something* every day.
  A bad source is skipped. A story that cannot be written becomes a plain card. A
  bad morning becomes a shorter "quiet" edition or a "fallback" list. It never
  silently skips a day and never shows a broken page.

---

## 3. Access checklist (when you take over)

Before you can operate the project you need access to these accounts and
machines. Get each one, then confirm it with the check in the last column.

| # | What | Why you need it | How to confirm you have access |
|---|------|-----------------|--------------------------------|
| 1 | **The GitHub repo** | The code, the committed editions, and the publish workflow live here | You can see the repo and its Actions tab |
| 2 | **GitHub Actions secrets** (repo Settings -> Secrets and variables -> Actions) | The daily publish reads all credentials from here | You can see the list of secret names (values are hidden) |
| 3 | **The mini PC** (SSH login) | The collector runs here every 3 hours | You can SSH in and run `systemctl --user list-timers` |
| 4 | **Cloudflare R2** (the account with the R2 Data Catalog and the audio bucket) | All the data tables and the daily MP3 live here | Spike 1 below passes |
| 5 | **Anthropic API** (Claude) | Scoring, editor, writers, audio script | Spike 2 below passes |
| 6 | **Google AI (Gemini)** | Text-to-speech for the audio | `spikes/check_tts.py` lists TTS models |
| 7 | **healthchecks.io** | The two "dead man's switch" alerts | You can see both checks on the dashboard |
| 8 | **GoatCounter** | Website traffic analytics | You can open the analytics dashboard |
| 9 | **Keyed news sources** (NewsAPI, Finnhub, FRED) | Only if these are enabled | The keys are in the secrets and the sources are `enabled: true` |

The credentials themselves live in two places and **must be the same in both**:

- **Locally:** a `.env` file in the repo root (never committed). The full list of
  names is below.
- **In CI:** GitHub Actions secrets with the same names.

The 15 credential names:

```
R2_CATALOG_URI  R2_WAREHOUSE  R2_TOKEN          # the Iceberg data tables
R2_S3_ENDPOINT  R2_ACCESS_KEY_ID  R2_SECRET_ACCESS_KEY  R2_AUDIO_BUCKET  R2_AUDIO_PUBLIC_BASE   # the audio MP3 bucket
ANTHROPIC_API_KEY                               # Claude (scoring/editor/writer/audio script)
GEMINI_API_KEY                                  # Gemini text-to-speech
NEWSAPI_KEY  FINNHUB_KEY  FRED_KEY              # keyed sources (optional)
HEALTHCHECKS_PUBLISH_URL  HEALTHCHECKS_COLLECT_URL   # monitoring
```

Only one module ever reads these: [`src/config.py`](src/config.py). If you find a
bare `os.environ` anywhere else, that is a bug.

**Confirming credentials work (the "spikes").** The `spikes/` folder has tiny
scripts that test one credential each. Run them when you take over or after
rotating a key. See [`spikes/README.md`](spikes/README.md).

```bash
uv run python spikes/check_iceberg.py       # R2 data tables reachable?
uv run python spikes/check_anthropic.py     # Claude key works?
uv run python spikes/check_embeddings.py    # local embeddings install works?
uv run python spikes/check_tts.py           # Gemini key works?
```

---

## 4. Where everything lives

| Thing | Where it is | How to look at it |
|-------|-------------|-------------------|
| The live website | GitHub Pages (URL is `site` + `base` in `site/astro.config.mjs`) | Open it in a browser |
| The published editions (the record) | `site/content/editions/*.json` in the repo, one file per day | Open the JSON, or `norm.py status` |
| Raw collected items | `bronze.raw_items` (Iceberg on R2) | `norm.py table bronze --date <day>` |
| Grouped, rated stories | `silver.story_clusters` (Iceberg on R2) | `norm.py table silver --date <day>` |
| Permanent archive | `gold.raw_items`, `gold.story_clusters`, `gold.editions` (Iceberg on R2) | `norm.py table editions` |
| One row per job run | `ops.run_log` (Iceberg on R2) | `norm.py runlog` |
| The daily audio MP3 | An R2 object bucket at `/audio/YYYY-MM-DD.mp3` | The URL is in the edition's `audio.url` |
| The daily publish | GitHub Actions -> `publish.yml` | The repo's Actions tab |
| The collector | The mini PC (systemd timer) | SSH in, `systemctl --user list-timers` and `journalctl` |
| Monitoring | healthchecks.io | The healthchecks dashboard |
| Traffic | GoatCounter | The GoatCounter dashboard |

The four Iceberg "layers" are just stages of the same data: **bronze** is raw,
**silver** is grouped and rated, **gold** is the permanent record, and **ops** is
the run log.

---

## 5. Daily and weekly checks

### Every morning (about 2 minutes)

Do this after 6:00 am Eastern, when the day's edition should exist.

1. **Open the website.** Is today's date on it? Does it look right?
2. **Run the status command:**
   ```bash
   uv run python scripts/norm.py status
   ```
   You want to see: the latest edition is today, and `editor`, `audio`, and
   `archive` all ran a few hours ago with status `success` (or `partial`, which
   is fine, see below). The `collector` should have run within the last few
   hours.
3. **Check healthchecks.io.** Both checks (publish and collector) should be
   green. A red check is the earliest warning that a job did not run at all.

**`success` vs `partial` vs `failed`:**

- `success` - the job did everything cleanly.
- `partial` - the job finished and published, but something degraded (a source
  was skipped, a story published without its article, or the reading level was
  over the limit). **This is normal and expected on many days.** Read the `notes`
  to see what degraded. You only act if the same thing happens every day.
- `failed` - the job did not finish. This needs attention. Go to section 7.

### Once a week (about 10 minutes)

This is the review from SPEC section 8. It keeps quality from drifting.

1. `uv run python scripts/norm.py cost --days 7` - are you on track for under
   $25/month? (Note: manual re-runs inflate this; one real publish per day is the
   true rate.)
2. `uv run python scripts/norm.py runlog --days 7` - how many `partial` or
   `failed` runs? Any pattern (the same source failing, the same readability
   flag)?
3. Skim a few editions on the site. Are stories being grouped sensibly? Are
   scores reasonable? Is the writing plain?
4. If clustering looks too loose or too tight, or scores look off, the knobs are
   `cluster_threshold` and the scoring rubric. See section 9 before changing
   them.

---

## 6. How to inspect state (the tools)

You have three ways to look at what the pipeline is doing. In order of how often
you will use them:

### a) The status tool (start here)

`scripts/norm.py` (section 1) is read-only and safe. It is the fastest way to see
health, recent runs, table contents, and cost.

### b) A dry run of any stage

Every stage can be run with `--dry-run`, which does the real work up to the point
of spending money or writing anything, then prints a summary and stops. **A dry
run makes no AI calls and changes nothing** (except the audio stage, which does
make its one script call so you can see the dialogue; it still skips the
expensive text-to-speech and the upload).

```bash
uv run python -m src.collector --dry-run          # what would be collected right now
uv run python -m src.silver.run_silver --dry-run  # how today's items would cluster
uv run python -m src.editor.run_edition --dry-run # what kind of edition today would be
uv run python -m src.audio.run_audio --dry-run    # the script and its word count
uv run python -m src.archive --dry-run            # what would be archived
```

Add `--verbose` (or `-v`) to any of them for more detail, and `--date
YYYY-MM-DD` to look at a past day.

### c) The published editions on disk

The `site/content/editions/` folder is the permanent publication record. Each
file is one day's `edition.json`. You can open any of them directly to see
exactly what was published, including the `edition_type`, the stories, and
whether audio was attached.

### The dashboards

- **GitHub Actions tab** - the publish workflow's runs and their logs.
- **healthchecks.io** - whether the two scheduled jobs are checking in.
- **GoatCounter** - website traffic.

---

## 7. Incident response (what to check when something is wrong)

Find your symptom below. Each one lists the likely causes, what to check in order,
how to fix it, and how to confirm the fix.

A general principle first: **read the `notes` field in `ops.run_log`.** Every job
writes why it ended the way it did. `norm.py status` and `norm.py runlog` both
show it. Nine times out of ten the notes tell you what happened.

---

### 7.1 The site is down or not showing today's edition

**Likely causes:** the publish did not run, the deploy failed, or the browser is
showing a cached copy.

**Check, in order:**

1. Hard-refresh the page (it may be cached). Try an incognito window.
2. `uv run python scripts/norm.py status`. Is the latest edition today?
   - **If the latest edition IS today** but the site is old, the *build/deploy*
     failed, not the edition. Go to 7.3, step "Astro build / deploy".
   - **If the latest edition is NOT today**, the publish did not produce one. Go
     to 7.2.
3. Check GitHub Pages is enabled (repo Settings -> Pages) and pointing at the
   Actions deployment.

---

### 7.2 There is no new edition this morning

**Likely causes:** the 6am publish did not run, or the schedule gate blocked it.

**Check, in order:**

1. Open the repo's **Actions** tab and look at the `publish` workflow. Did it run
   today?
2. **If it did not run at all:** the schedule may not have fired, or the gate
   exited early. The publish is timed to 6:00 am Eastern using a dual-cron trick
   (it fires at 10:00 and 11:00 UTC and lets through whichever is 6am Eastern that
   day, correct across daylight saving). If nothing fired, GitHub Actions
   schedules can be delayed or skipped when a repo is low-activity. **Just run it
   manually** (see below).
3. **If it ran but the gate job blocked the publish job:** that is expected for
   the cron that is not the 6am one. Only a problem if *both* were blocked.

**Fix - publish now, manually:**

Either from the Actions tab ("Run workflow" on `publish`, set `force` to `true`),
or from the command line:

```bash
gh workflow run publish.yml -f force=true
```

`force=true` bypasses the 6am-Eastern gate and publishes immediately.

**Verify:** watch the run in the Actions tab, then `norm.py status` should show
today's edition and the site should update within a few minutes of the deploy.

---

### 7.3 The publish workflow failed

Open the failed run in the Actions tab and find which **step** failed. The steps
run in this order; each one below tells you what it means and what to do.

1. **Build edition** (`src.editor.run_edition`). This step almost never fails
   outright, because it is built to fall back rather than crash. If it *did* fail,
   the cause is usually the R2 catalog being unreachable (see 7.7) or the
   Anthropic key being invalid (see 7.6). Check `norm.py runlog --job editor` for
   the notes.
2. **Audio build** (`src.audio.run_audio`). Audio is optional. This step is
   designed never to block the publish: any failure just means "no audio player
   today." If the whole *step* errored (not just skipped audio), it is likely the
   Gemini key or the R2 audio bucket. See 7.8.
3. **Commit edition.** Fails only on a git permission problem. Confirm the
   workflow has `contents: write` permission (it does by default in `publish.yml`).
   "Nothing to commit" is not a failure.
4. **Astro build** (`npm run build` in `site/`). A build failure here usually
   means a committed `edition.json` does not match the site's schema, or a code
   change broke a component. Reproduce locally:
   ```bash
   cd site && npm ci && npm run build
   ```
   The error will name the file and field. If it is a bad edition file, see 7.12.
5. **Deploy** (to GitHub Pages). Fails on a Pages configuration problem or a
   GitHub outage. Re-run the workflow; if it keeps failing, check
   [GitHub status](https://www.githubstatus.com/) and the repo's Pages settings.
6. **Ping healthchecks.** This only runs if the deploy succeeded. If the deploy
   failed, this step never runs, the ping is missed, and healthchecks.io alerts
   you. That is the design.
7. **Archive to gold** (`src.archive`). Runs last, on purpose, so a failure here
   never costs the published edition. If it fails, the edition is still live. Fix
   the cause (usually R2, see 7.7) and re-run just the archive for that day:
   ```bash
   uv run python -m src.archive --date <the day>
   ```

**After any fix**, you can re-run the whole publish safely with `gh workflow run
publish.yml -f force=true`. Every stage is idempotent: re-running a day corrects
it rather than duplicating it.

---

### 7.4 The collector stopped (no fresh items)

**Symptom:** `norm.py status` warns the collector is stale, or healthchecks.io's
collector check is red.

**Likely causes:** the mini PC is off or offline, its timer is disabled, or it
cannot reach R2.

**Check, in order (SSH into the mini PC first):**

1. Is the machine on and online? Can you SSH in?
2. Is the timer active?
   ```bash
   systemctl --user list-timers          # find the collector timer
   systemctl --user status <timer-name>  # is it enabled and scheduled?
   ```
   (The exact unit name was set during setup, SPEC 6.2 / SETUP.md M5. If you are
   not sure of the name, `list-timers` shows it.)
3. Look at the recent logs:
   ```bash
   journalctl --user -u <service-name> -n 100 --no-pager
   ```
   The error is usually a network problem or an R2 credential problem.
4. Run one cycle by hand to see the error live:
   ```bash
   uv run python -m src.collector --dry-run   # fetch only, writes nothing
   ```

**Fix:**

- If the timer was stopped: `systemctl --user start <timer-name>` and
  `systemctl --user enable <timer-name>`.
- If the mini PC is down and will stay down a while, turn on the **backup
  collector** in GitHub Actions so collection continues. Edit
  [`.github/workflows/collect_fallback.yml`](.github/workflows/collect_fallback.yml)
  and uncomment its `schedule` block, or trigger it manually:
  ```bash
  gh workflow run collect_fallback.yml
  ```
  The collector is idempotent, so running the mini PC and the fallback at the same
  time is harmless (duplicates are dropped).

**Do not panic about a missed cycle.** The collector looks back 6 hours each run
but only runs every 3, so the windows overlap. One missed cycle is backfilled by
the next one automatically.

**Verify:** `norm.py runlog --job collector` shows a fresh `success` row, and the
collector healthcheck goes green.

---

### 7.5 A "fallback" or "quiet" edition was published

These are the system protecting itself. Whether it is fine or a problem depends
on which one and why.

**A `quiet` edition** (fewer stories, a 3-point glance) means there were fewer
usable stories than the threshold for a normal edition. On a genuinely slow news
day this is correct behavior. It is only a problem if it happens on a day you know
was busy, which points at a **collection or clustering problem** (go to 7.4, then
7.11).

**A `fallback` edition** (just a notice and a ranked top-10 list) means one of two
things:

1. **The editor AI failed validation twice.** Check
   `norm.py runlog --job editor`; the notes will say "editor output invalid
   twice". This is usually a transient model issue. **Fix:** re-run the edition:
   ```bash
   uv run python -m src.editor.run_edition --date <the day>
   ```
   then re-run the rest of the publish (7.3). If it fails twice again, the editor
   prompt or the Anthropic account may have a real problem (see 7.6).
2. **There was almost no usable data at 6am.** The notes will say "too little
   usable data". This points back at the collector (7.4).

To see which case you are in before re-running, do a dry run:
```bash
uv run python -m src.editor.run_edition --date <the day> --dry-run
```
It prints the edition type it would choose and how many usable clusters it found.

---

### 7.6 Anthropic (Claude) problems

**Symptoms:** the editor falls back repeatedly, scoring stores lots of null
scores, or a stage's notes mention an Anthropic/authentication error.

**Check:**

1. Is the key valid and in funds?
   ```bash
   uv run python spikes/check_anthropic.py
   ```
   If this fails, the key is wrong, expired, or the account is out of credit or
   rate-limited.
2. Check the Anthropic console for billing and rate limits.

**Fix:** correct the key in **both** `.env` (local / mini PC) and the GitHub
Actions secret `ANTHROPIC_API_KEY`, then re-run the affected stage. If it is a
rate limit, wait and re-run.

**Note:** a single bad scoring call is not an incident. Scoring contains its own
failures (a cluster that will not score twice is stored with a null score and the
editor ignores it). You only act when *many* calls fail.

---

### 7.7 The data tables are unreachable (R2 catalog)

**Symptoms:** `norm.py` prints "Could not connect to the R2 catalog", or a stage
fails with a catalog/authentication error.

**Check:**

1. ```bash
   uv run python spikes/check_iceberg.py
   ```
   This confirms whether you can reach the R2 Data Catalog and read/write a test
   table.
2. If it fails, the cause is one of: `R2_CATALOG_URI`, `R2_WAREHOUSE`, or
   `R2_TOKEN` being wrong or expired, or a Cloudflare outage.

**Fix:** correct the three catalog credentials in `.env` and in the Actions
secrets, then re-run the spike. Check
[Cloudflare status](https://www.cloudflarestatus.com/) if the credentials are
known-good.

**Note:** these three are the only *required* credentials. The pipeline refuses
to start without them, on purpose, so a missing catalog fails loudly at the top of
a run rather than halfway through.

---

### 7.8 Audio is missing (no player on the site)

Audio is optional, so a missing player is a degraded day, not an outage. The
edition still publishes.

**Check `norm.py runlog --job audio`.** The notes tell you which of these it was:

- "fallback edition carries no audio" - correct; fallback editions have no audio.
- "script failed twice" - the audio-script AI could not produce a valid dialogue.
  Usually transient; re-run: `uv run python -m src.audio.run_audio --date <day>`.
- "TTS failed" - Gemini text-to-speech failed. Check the Gemini key
  (`spikes/check_tts.py`) and the Gemini console. Correct `GEMINI_API_KEY` in both
  places if needed.
- "upload failed" - the MP3 could not be uploaded to the R2 audio bucket. Check
  the five audio credentials (`R2_S3_ENDPOINT`, `R2_ACCESS_KEY_ID`,
  `R2_SECRET_ACCESS_KEY`, `R2_AUDIO_BUCKET`, `R2_AUDIO_PUBLIC_BASE`).

**Fix and re-voice one day:**
```bash
uv run python -m src.audio.run_audio --date <the day>
```
Re-voicing is cheap: if the MP3 already exists in R2 it is reused, not
regenerated. After re-voicing, re-run the publish (7.3) so the site rebuilds with
the audio.

---

### 7.9 Stories are publishing without their article (plain cards)

**Symptom:** stories show as flat cards with no "Read the full story" expander;
notes say "stories published without an article (thin grounding)".

**What it means:** the writer stage is only allowed to write an article when the
story has enough real source text to ground it (decision #16: it must not invent
facts). If a story's sources gave only a one-line summary, it publishes as a plain
card instead. A few of these per day is normal.

**When it is a real problem:** if *many* stories lack articles every day, the
enrichment step (which fetches the full article text) may be failing for a source.

**Check:** look at which sources are affected. A source whose article pages cannot
be fetched (paywalled, blocked, or a redirect shim like Google News) will always
produce thin cards. This is a known trade-off recorded in
[`config/sources.yaml`](config/sources.yaml) and
[`config/pipeline.yaml`](config/pipeline.yaml) (the `enrich.skip_hosts` list and
the source comments).

**Fix:** replace the thin source with a direct publisher RSS feed in
`config/sources.yaml` (whose article pages extract cleanly), or accept the flat
cards for that source. Do not lower the `min_grounding_chars` floor to force
articles; that would let the writer invent facts, which the floor exists to
prevent.

---

### 7.10 The readability gate keeps flagging

**Symptom:** notes say "readability gate exceeded after revision"; the run is
`partial`.

**What it means:** the edition read harder than the grade-9 target even after the
automatic rewrite passes, so it published anyway and flagged itself. Publishing
beats blocking. One flagged day is not an incident.

**When it is a problem:** if it flags most days, the writing is drifting hard.

**Fix options (in order of preference):**

1. Increase the rewrite budget in `config/pipeline.yaml`:
   `editor.readability_max_passes` (each pass costs a little more AI but pulls the
   grade down). It is already tuned to clear the limit reliably; raising it is the
   first lever.
2. Tighten the writing prompts in [`prompts/`](prompts/) (bump the version, see
   section 9).

**Verify:** re-run the edition for a day and check `norm.py runlog --job editor`
no longer flags it.

---

### 7.11 One or more sources (adapters) are failing

**Symptom:** a collector run is `partial`; notes list "adapters failed: ...".

**What it means:** one source failed and was skipped. **One failing source never
fails the run** (SPEC 6.1). The rest still came through.

**Check which source and why:**
```bash
uv run python -m src.collector --dry-run
```
The dry run prints per-source item counts and lists any that failed. Common
causes: the source is down, moved its feed URL, started returning 403 (blocking
our requests), or a keyed source's API key expired.

**Fix:**

- **Feed moved:** update its `feed_url` in `config/sources.yaml`.
- **Source blocking us / down for good:** set `enabled: false` for it in
  `config/sources.yaml`, or replace it with another feed on the same topic.
- **Keyed source key expired:** fix the key (`NEWSAPI_KEY` / `FINNHUB_KEY` /
  `FRED_KEY`) in both places.
- **Temporary outage:** do nothing; it will come back on the next cycle.

**Verify:** the next `norm.py runlog --job collector` is `success`, or the failing
source is gone from the notes.

---

### 7.12 A bad edition was published (wrong or broken content)

Because the committed `edition.json` files are the permanent record, you fix a bad
day by correcting or rebuilding that day, then re-deploying.

**Option A - rebuild the day from the pipeline** (preferred, if the source data is
still good and the day has not been archived yet):
```bash
uv run python -m src.editor.run_edition --date <the day>
uv run python -m src.audio.run_audio --date <the day>
```
Then commit the changed file and re-run the publish (7.3).

**Option B - hand-fix the file** (for a small, specific correction): edit
`site/content/editions/<date>.json` directly, then rebuild and redeploy the site.
Validate your edit first by building locally (`cd site && npm run build`); the
build fails if your JSON does not match the schema, which stops you from shipping
a broken file.

**Note on already-archived days:** after the archival job runs, that day's bronze
and silver partitions are dropped (they live in `gold` now). Re-running the
edition for such a day will see no source data and would try to publish an empty
fallback, so the pipeline deliberately *keeps the already-published edition*
instead. For those days, use Option B.

---

### 7.13 Costs are climbing

See section 10.

---

### 7.14 Clustering looks wrong (duplicates, or unrelated stories merged)

**Symptom:** the same story appears as two separate stories, or two unrelated
stories are merged into one.

**What controls it:** `silver.cluster_threshold` in `config/pipeline.yaml`
(currently 0.82). Higher means stricter (more separate clusters, risk of
duplicates); lower means looser (more merging, risk of unrelated items together).

**Before changing it:** this number is calibrated against the specific embedding
model and was chosen to be observed for two weeks before trusting (decision #2).
Look at several days with `norm.py table silver --date <day>` first. A change here
affects every future day, so treat it as a tuning decision, not a quick fix, and
change it in small steps.

---

## 8. Manual operations (the levers you have)

All of these are safe to run because every stage is idempotent.

| I want to... | Command |
|--------------|---------|
| See health right now | `uv run python scripts/norm.py status` |
| Publish today's edition now (skip the 6am gate) | `gh workflow run publish.yml -f force=true` |
| Rebuild one past day's edition | `uv run python -m src.editor.run_edition --date YYYY-MM-DD` |
| Re-voice one past day | `uv run python -m src.audio.run_audio --date YYYY-MM-DD` |
| Re-cluster/score one past day | `uv run python -m src.silver.run_silver --date YYYY-MM-DD` |
| Re-archive one past day | `uv run python -m src.archive --date YYYY-MM-DD` |
| Collect once by hand | `uv run python -m src.collector` |
| Run the backup collector in CI | `gh workflow run collect_fallback.yml` |
| Preview any stage without spending money | add `--dry-run` to any stage command |

**Backfilling after a mini PC outage:** the collector's overlapping window heals
short gaps by itself. For a longer gap, run the collector a few times manually
(each run pulls recent items and dedups), then run silver for the affected day.

**Enabling a keyed source:** put its key in `.env` and the Actions secrets, then
set `enabled: true` for it in `config/sources.yaml`.

**Disabling a broken source:** set `enabled: false` for it in
`config/sources.yaml`. No code change needed.

**Rotating a credential:** change it in **both** `.env` (local and mini PC) and
the matching GitHub Actions secret, then run the relevant spike in `spikes/` to
confirm it works.

---

## 9. Making changes safely

The project has strict rules, in [`CLAUDE.md`](CLAUDE.md). The ones that matter
most for an operator:

- **No Spec, No Code.** If a behavior is not covered by SPEC.md or DESIGN.md,
  propose an addition and get it approved before building it. Do not infer new
  behavior from what seems reasonable.
- **Never use an em dash** in any generated text, prompt, comment, or copy.
- **URLs come from one place.** The site's absolute URL and base path are defined
  only in [`site/astro.config.mjs`](site/astro.config.mjs). Everything derives
  from those two values. A hardcoded self URL anywhere is a bug.
- **Frozen vs. tunable.** Model ids, thresholds, the source list, and
  `shortener_hosts` are tunable config changes. But the URL-cleanup rules in
  `src/adapters/base.py` are **frozen**: they feed the deduplication hash, and
  changing them breaks dedup against every stored item. Do not touch them without
  a version bump and a migration.

**Always run the checks before and after a change:**

```bash
uv run pytest -q                                       # the test suite (offline)
uv run python .claude/skills/milestone-verify/verify.py  # the full gate
```

The gate runs the tests, validates the sample editions in `site/fixtures/`
against the schema, and greps the site for hardcoded URLs. A green gate means the
repo is still in a publishable state. (For the URL half of the gate to be
meaningful, build the site first: `cd site && npm run build`.)

**Changing a prompt:** the prompts in [`prompts/`](prompts/) are versioned
(`_v1`). Significant changes should bump to `_v2` rather than editing in place, so
the stored `prompt_version` in the tables stays honest for the weekly review.

**The pre-launch migration** (moving from the personal account to a project org)
is a planned, one-time procedure in SPEC section 13. Its only code change is the
two values in `astro.config.mjs`. Follow that section exactly when the time comes.

---

## 10. Cost management

The budget is **under $25 a month** (SPEC section 9). Almost all of it is AI
calls; storage, hosting, and monitoring are effectively free.

**Watch the spend:**
```bash
uv run python scripts/norm.py cost --days 7
```
This sums `ai_cost_estimate_usd` from the run log per day. Remember that manual
re-runs during debugging inflate the number; in steady state there is roughly one
publish per day.

**Rough monthly shape (SPEC section 9):**

| Line item | Estimate |
|-----------|----------|
| Scoring (small model, cached) | $4-8 |
| Editor + writer articles | $6-10 |
| Audio script + text-to-speech | $3-6 |
| Embeddings (local) | $0 |
| Storage, hosting, monitoring | ~$0 |

**If you are over budget, the levers (in order):**

1. Lower `max_items_per_run` for chatty sources in `config/sources.yaml` (fewer
   items to score).
2. Lower `editor.readability_max_passes` in `config/pipeline.yaml` (fewer rewrite
   calls, at the cost of a slightly higher reading grade).
3. Disable the most expensive or least valuable sources.
4. Shorten articles (a writing-prompt change).

Scoring is already kept cheap two ways: the rubric is prompt-cached (so it is
billed at a fraction after the first call), and clusters are only re-scored when
they are new or have grown (decision #6). You should not normally need to touch
those.

---

## 11. When to stop and escalate

Handle these yourself: skipped sources, `partial` runs, one-off fallback or quiet
editions, re-running a day, rotating a key, disabling a broken source.

Escalate to the owner (Milind) when:

- **SPEC.md and DESIGN.md disagree** about something. Never resolve a conflict
  between them yourself.
- A change you are considering is **not covered by SPEC or DESIGN** (the No Spec,
  No Code rule).
- A credential needs to be **reissued under a new account**, or you are doing the
  **pre-launch migration** (SPEC section 13).
- The same failure repeats every day and none of the fixes here resolve it.

## Reference map (where each subsystem is documented)

| Subsystem | Code | Deep docs |
|-----------|------|-----------|
| Sources / collection | `src/adapters/`, `src/collector.py`, `src/enrich.py` | SPEC 6.1-6.2, `src/adapters/README.md` |
| Storage (Iceberg on R2) | `src/storage.py`, `src/bronze.py` | SPEC 6.3 |
| Dedup / cluster / score | `src/silver/` | SPEC 6.4, `src/silver/README.md` |
| The edition | `src/editor/` | SPEC 6.5, `src/editor/README.md` |
| Readability | `src/editor/readability.py` | SPEC 6.5, DESIGN 8 |
| Audio | `src/audio/` | SPEC 6.7, `src/audio/README.md` |
| Publish workflow / scheduling | `.github/workflows/`, `src/schedule.py` | SPEC 6.8, `.github/workflows/README.md` |
| Archive / gold | `src/archive.py` | SPEC 6.9 |
| Monitoring / run log | `src/runlog.py`, `src/health.py` | SPEC section 8 |
| Config / secrets | `src/config.py`, `config/` | SPEC 6.10, `config/README.md` |
| The website | `site/` | DESIGN.md, `site/README.md` |
| Cost | (the run log) | SPEC section 9 |
| Failure behavior | (throughout) | SPEC section 7 |
