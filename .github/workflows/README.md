# `.github/workflows/` - GitHub Actions automation

Two workflows. One publishes the newsletter every morning; the other is a backup
launcher for the all-day collector.

## `publish.yml` - the daily 6am publish

This is the workflow that builds and ships the newsletter. It implements the
publish sequence in SPEC 6.8.

**Scheduling (the DST trick).** GitHub cron runs in UTC and cannot express "6am
US Eastern," which drifts by an hour twice a year with daylight saving. So the
workflow fires at **two** times, `0 10 * * *` and `0 11 * * *` UTC, and a small
`gate` job runs `src.schedule.is_publish_time(...)` to let exactly one of them
through, whichever is 6:00 am Eastern that day. The DST logic is Python (pinned
by tests), not YAML, so there is only one copy of it. You can also trigger it
manually with `force: true` to bypass the gate.

**What the publish job does, in order:**

1. Check out the repo, install Python (uv) and Node deps.
2. **Build edition** (`python -m src.editor.run_edition`): read silver, run the
   editor and writer AI stages, run the readability gate, write `edition.json`.
3. **Audio build** (`python -m src.audio.run_audio`): write the dialogue script,
   render the MP3 with Gemini TTS, upload it to R2, inject the audio block.
4. **Commit the edition** to `site/content/editions/` (this is the permanent
   publication record).
5. **Astro build** the site from the committed editions, then **deploy to
   GitHub Pages**.
6. **Ping healthchecks.io.** This is only reached if the deploy succeeded, so a
   failed deploy shows up as a *missing* ping and the dead man's switch alerts.
7. **Archive to gold** (`python -m src.archive`): fold the day into the permanent
   record and drop the daily partitions. Runs last so a failure here never costs
   the published edition.

**Concurrency** is set so only one publish runs at a time and a run is never
cancelled midway (a half-finished deploy or archive is worse than waiting).

All credentials come from **GitHub Actions secrets** (the `env:` block maps them
in); nothing sensitive is in the repo.

## `collect_fallback.yml` - the backup collector

The collector normally runs every 3 hours on an always-on "mini PC" (via a
systemd timer). This workflow is the **disabled** Actions fallback for when that
machine is down. It is `workflow_dispatch` (manual) by default; the `schedule`
block is commented out. Because the collector is idempotent (bronze dedups),
running it here at the same time as the mini PC is harmless. It runs a collect
cycle and then the silver stage.

## A note on secrets and the pre-launch migration

Secrets do not transfer when a repo moves. SPEC section 13 (the pre-launch
migration from a personal account to a project org) re-adds all Actions secrets
in the new repo as one of its steps. The only code change in that migration is
the two URL values in `site/astro.config.mjs`.
