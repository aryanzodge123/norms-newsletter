# Proposed spec addition: alert when the collect workflow fails after collecting

**Status: approved 2026-10-20.** The three text changes below are in SPEC.md
as written, and the step is in `collect.yml`. This document stays as the
reasoning behind them, the way `PROPOSED-SPEC-tts-resilience.md` does.

Both open questions were answered at approval: decision #27 covers the publish
check only, so this widens the collector check as proposed; and the mini PC no
longer runs the collector, so no local success ping can clear the alert.

This exists because an expired Anthropic key cost the 2026-10-18 edition, with
ten hours of warning that nothing passed on.

## The evidence

The Anthropic key expired around 2026-10-17 23:00Z. Every collect run after
that failed the same way:

| Run started | Collect step | Silver step |
| --- | --- | --- |
| 2026-10-17 23:01Z | success | failure |
| 2026-10-18 04:18Z | success | failure |
| 2026-10-18 10:53Z | success | failure |
| 2026-10-18 15:46Z | success | failure |
| 2026-10-18 20:30Z | success | failure |

Silver failed on its first API call, the prompt-length check in
`ensure_cacheable`, with `401 invalid x-api-key`. Nothing was written to
silver for 2026-10-18, so the publish at 09:35Z had no scored clusters and
published a fallback edition with no audio. That broke the 14-day streak.

**The collector cadence check stayed green the whole time.** The Collect step
pings healthchecks itself (`src/collector.py`), and collection does not need
the Anthropic key, so each run reported success before Silver ran and failed.
The only signal was a red Actions run. GitHub emails a scheduled workflow's
failure to the account that last edited its cron line, which for `collect.yml`
is a single personal account, not the place this project sends alerts.

The key was rotated at about 20:40Z on 2026-10-18 and the next run went green.
An alert at 23:01Z would have left more than ten hours to rotate it before
the publish.

**The crash itself is correct and should stay.** With a bad key every scoring
call fails, so no change to silver's error handling could have produced a real
edition. Failing early with a clear `AuthenticationError` is the right
behavior. What is missing is anyone hearing about it.

## Proposal

Fold Silver's outcome into the collector cadence check. When any step of the
collect workflow fails, a final step pings the check's `/fail` URL. One step
in `collect.yml`, using the `HEALTHCHECKS_COLLECT_URL` secret the job already
has:

```yaml
      # SPEC section 8 / decision #68: a failed step after Collect (Silver,
      # most likely) would otherwise leave the check green, because Collect
      # has already pinged success. This turns the check red within the run.
      - name: Report failure to the collector check
        if: failure()
        run: curl -fsS -m 10 --retry 3 "$HEALTHCHECKS_COLLECT_URL/fail" || true
```

`|| true` is there for the same reason `health.ping` never raises: a failed
ping must not change the run's outcome.

**Why a workflow step rather than a ping inside `run_silver.py`.** The step
catches every way the job can fail: a Python exception, a crash that never
reaches a `finally` (the 2026-07-22 segfault, exit 139), and a failed
`uv sync`. A ping in Python catches only the first. It is also one line, with
no new code path to test.

**Why this check and not a new one.** The cadence check already means "the
collector is not producing usable data": section 8 extends it from a stalled
process to a blind one (zero items fetched). A collector whose items never get
scored is the same failure as far as the edition is concerned. A third check
would be one more thing to configure and watch for no extra information.

### Text changes to SPEC.md

**Section 7, failure table**, a new row after "All sources return nothing":

| Failure | Behavior |
| --- | --- |
| Silver fails (bad key, crash) | Collect workflow pings collector check `/fail`; next successful run clears it |

**Section 8, the healthchecks.io paragraph.** After "...not just a stalled
process or an R2 failure." add:

> The collect workflow also pings `/fail` when any of its steps fails, so a
> silver failure after a successful collection (an expired API key, a crash)
> turns the same check red instead of hiding behind the collector's success
> ping (decision #68).

**Section 10, decision log**, a new row:

| 68 | A failed collect workflow pings the collector cadence check's `/fail`, so a silver failure alerts through the channel the project already watches. On 2026-10-17 to 18 an expired Anthropic key failed silver five runs in a row while the Collect step reported success each time, and the day published a fallback with ten hours of unused warning. The ping is a workflow step rather than code so it also covers crashes that never reach Python's error handling. This is the collector check, not the publish check; decision #27's rule that the publish check stays a pure published-or-not signal is untouched |

## Does this conflict with decision #27?

I do not think so, but it is the reading that needs your call (CLAUDE.md:
conflicts go to Milind, never resolved here). Decision #27 and section 8's
"Two independent signals" paragraph say healthchecks answers only "did the
site publish." Read in context, both describe the **publish** check: the
paragraph contrasts it with the red Actions run for a degraded edition. The
collector check already answers a different question, and already pings
`/fail` for a blind collector. This proposal widens that second check only.
If you read #27 as covering every healthchecks check, this proposal conflicts
with it, and the alternative is a third healthchecks check used only for
silver. That costs one new check and one new secret.

## What this does not do

- It does not save a day like 2026-10-18 by itself. It turns a silent failure
  into an alert with hours to spare; someone still has to rotate the key.
- It does not alert on a partial silver run (some clusters scored null). That
  is contained by design (SPEC 6.4c) and stays a run-log matter.
- **A local collector run can clear the alert.** If the mini PC still runs
  `src.collector` against the same check, its success ping marks the check
  green again until the next Actions run fails. Whether the mini PC still runs
  is unconfirmed; if it does not, this does not arise.

## How to verify it once built

1. Set `HEALTHCHECKS_COLLECT_URL` locally and, on a branch, make Silver fail
   on purpose (for example a step with `exit 1` after Collect). Dispatch the
   workflow and confirm the check turns red within the run.
2. Remove the forced failure, dispatch again, and confirm the next success
   ping clears it.
3. A RUNBOOK line under the Anthropic key section: a red collector check
   whose run shows `silver run failed: AuthenticationError` means rotate the
   key (SETUP.md 2.1, then the Actions secret).
