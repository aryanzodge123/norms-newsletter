# Stress test findings, 2026-07-23

Status: **working note, not spec.** A full-project stress test run on
2026-07-23. Findings 1 and 2 are being planned and implemented separately
(they are the highest-value pair and share a root cause). This file holds
the remaining findings so they are not lost. Each needs the usual
spec-first, one-milestone treatment before any code.

Method: failure injection at every pipeline stage, workflow inspection,
analysis of the live `ops.run_log` (105 rows, 2026-07-20 to 07-24), plus
hygiene, spec-drift, and coverage sweeps. The probe file was temporary and
has been deleted; the repo is clean and all 443 tests pass.

---

## Being handled elsewhere (do not double-plan)

- **Finding 1: jobs do their riskiest work outside their own error
  handler.** Config load, catalog connect, and the first data read run
  before the `try`, so an R2 blip at 6am escapes `run()` and writes no
  `run_log` row at all. Same shape in all five entry points.
- **Finding 2: the workflow layer is fail-fast and undoes the in-code
  containment.** No `continue-on-error` or `if: always()` anywhere. A
  failure in audio, commit, npm, Astro, or deploy discards an
  already-built edition that is sitting on the runner's disk, never
  committed. Two real production instances on record (07-20, 07-21), both
  since fixed reactively, but the structural hole is open.

These two are in the active plan.

---

## HIGH 3. `partial` carries no signal, and green means nothing

Measured across the whole record:

| job | runs | breakdown |
|-----|------|-----------|
| editor | 18 | **partial=16**, success=1, failed=1 |
| collector | 28 | partial=8, success=20 |
| silver | 28 | success=28 |
| archive | 11 | success=11 |
| audio | 20 | success=18, partial=1, failed=1 |

`partial` is the editor's normal state (16 of 18), and healthchecks pings
green on every one, so a catastrophic morning is indistinguishable from an
ordinary one from the outside.

This is the observability work already discussed. The agreed direction:

- Keep healthchecks semantics as they are. Red means the site did not
  publish; green means it did. Do not overload it.
- Add one `run_log` column holding a small set of enumerated reason codes
  for why a run went `partial` (the real data shows a closed set of six:
  readability, thin grounding, adapters failed, editor-invalid fallback,
  thin-day fallback, audio script failed). Multi-valued: 5 of 25 partial
  rows already carry two reasons at once.
- "Was today degraded" becomes a query over those codes, not a second
  stored flag. Precision matters: a thin-day fallback is correct behavior
  and must not read as degraded, while an editor-invalid fallback must.
- Alert on the derived-degraded condition via a **failed GitHub Actions
  run at the very end**, after deploy and archive succeed. Site is live,
  healthchecks green, Actions red. Two independent signals that mean
  different things.
- Precedent for structured data in a string column already exists
  (`adapter_metrics`), so no new column type is needed.

The serious fallback is not hypothetical: the editor-invalid path already
fired twice in production on 2026-07-20, both green.

## MEDIUM 4. A collection cycle is dropped every night

Cron is `0 */3 * * *` (expects 21:00 and 00:00 UTC among others). Observed
three nights running:

```
 4.3h  07-21 22:02Z -> 07-22 02:21Z
 4.4h  07-22 22:02Z -> 07-23 02:26Z
 4.4h  07-23 22:02Z -> 07-24 02:24Z
```

GitHub fires the 21:00 slot about an hour late and effectively drops the
00:00 one, so nights get 7 cycles instead of 8. Low impact: adapters
backfill via `since`, so no items are lost. Likely resolves by shifting the
cron off the exact hour (an off-minute like `7 */3 * * *`). Cheapest
finding; do it last or fold it into other workflow work.

## MEDIUM 5. The editor prompt builder has no tests

`src/editor/run_editor.py` is referenced by no test. That includes
`build_user_message`, which renders the `prior_coverage` block into the
editor's prompt: the exact mechanism that makes continuing coverage work.
The gate that checks the editor's *output* has 15 tests; the *input* that
feeds it is unasserted. If the rendering silently broke, every test would
still pass and the editor would just stop being told about yesterday.

(The `build_user_message` hits in `test_score.py` are a different function
of the same name in `src/silver/score.py`.)

Fix: a small unit test asserting the `prior_coverage` block appears in the
built message when a candidate has prior coverage, and is absent otherwise.

## MEDIUM 6. A hardcoded URL the migration will not touch

```
src/adapters/base.py:42
    "+https://aryanzodge123.github.io/norms-newsletter/)"
```

The bot's User-Agent. SPEC 13 says the pre-launch migration changes the two
`astro.config` values "and nothing else", so afterward this string
advertises a dead address on every outbound request. Related: the
`check_urls` gate scans `site/src` and `site/dist` only and never scans
Python, which is why this passed.

Fix options: derive the User-Agent from config (cleanest, keeps rule 6
honest), or add it to the migration checklist in SPEC 13, or extend
`check_urls` to scan `src/`. Prefer the first.

## MEDIUM 7. Two adapters are chronically flaky

```
arxiv     errored in 6/28 collector runs (21%)
newsapi   errored in 2/28 runs ( 7%)
```

Each failure makes the collector `partial`, so these directly inflate
finding 3. Worth diagnosing (arxiv especially) so `partial` becomes rarer
and more meaningful before any signal is attached to it.

---

## What was healthy (recorded so it is not re-litigated)

- No secrets in any tracked file. `config.py` is the sole reader of env
  vars (SPEC 6.10).
- `silver` 28/28 and `archive` 11/11 have never failed.
- Audio containment works for its designed failures (script, TTS, MP3
  encode all return rc=0 and leave the edition intact).
- `schedule.py` DST logic is sound: compares Eastern wall-clock, correct on
  both sides of a transition; idempotency, not an exact minute, enforces one
  edition per day.
- The em dash rule holds, though by discipline: the six tracked occurrences
  are all legitimate (stripper constants and their tests). The
  milestone-verify gate does not actually check for em dashes, which is a
  latent gap worth closing when convenient.
- The fallback path is solid after this week's work.
