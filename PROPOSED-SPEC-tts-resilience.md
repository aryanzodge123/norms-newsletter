# Proposed spec addition: TTS resilience

**Status: a proposal. It governs nothing.** Under CLAUDE.md rule 1 these two
changes need a spec addition approved before the code that implements them.
Nothing here has been implemented. Where this document disagrees with SPEC.md,
SPEC.md wins.

This exists because the last four consecutive editions published without audio,
every one of them to a transient upstream failure that nothing tried a second
time, and because nothing in the system said so.

## The evidence

Five of the last six editions lost their audio. Each is the same stage failing
for a different transient reason.

| Date | TTS error | Call elapsed |
| --- | --- | --- |
| 2026-09-09 | `Server disconnected without sending a response.` | 4m23s |
| 2026-09-11 | `Server disconnected without sending a response.` | 5m11s |
| 2026-09-12 | `503 UNAVAILABLE ... high demand ... Please try again later.` | 2m29s |
| 2026-09-13 | `503 UNAVAILABLE ... high demand ... Please try again later.` | 1m25s |
| 2026-09-14 | `The read operation timed out` | 5m35s |

"Call elapsed" is measured from the last script-stage log line to the TTS
failure, so it is an upper bound on the call itself. The two five-minute rows
are consistent with `audio.tts_timeout_seconds: 300.0` firing. The two 503 rows
fail fast and are the cheapest possible thing to retry.

Across all 57 published editions, 43 carry audio and 14 do not. Ten of the
fourteen fall in the last twenty-one days, and four are consecutive and current.
This is a degrading trend, not a steady error rate.

**Every one of these runs behaved exactly as specified.** SPEC 7 says
`TTS fails -> Publish without audio row; log`, and that is what happened, five
times, correctly. The editions are otherwise intact: 2026-09-14 is a normal
edition with six sections and five briefly items. The publish workflow was green
each time because the audio build is the one stage classed non-blocking. Nothing
is broken against the spec as written. The spec as written is the thing worth
revisiting.

**One incidental result.** `PROPOSED-SPEC-edition-durability.md` closes by
listing as an open verification item that PR #43's `tts_timeout_seconds` had
never executed in production, because a fallback edition carries no audio. The
2026-09-14 `read operation timed out`, arriving about five minutes into the
call, is that timeout firing on a normal edition. It works. That item can close.

**The three proposals are independent.** They share a week of evidence, which is
why they are in one document, but any can be approved without the others.
Proposal A reduces how often audio is lost. Proposal B makes the loss visible
when it happens anyway, and proposal C records the number that would have
caught the sizing error underneath both. None substitutes for another, and B is
the most important: a system that loses audio and says so is in better shape
than one that loses it less often and stays quiet.

---

## Proposal A: retry a transient TTS failure before giving up the render

**Touches:** SPEC 6.7 (the audio build), SPEC 7's failure table. Proposed new
decision **#66**.

### The call has no second attempt

`src/audio/tts.py:170-181` is the whole of it. One `generate_content` call,
wrapped in a bare `except Exception`, everything converted into `TTSError`.
`src/audio/run_audio.py:119-121` catches that and returns "no audio". There is
no retry anywhere on the path.

So a 503 whose own message is "Spikes in demand are usually temporary. Please
try again later" is never tried again. The script stage above it gets two
attempts at the model. The render below it gets one.

### The spec already retries a transient failure of exactly this shape

SPEC 7 has a row for this pattern:

> | Silver write loses a commit race | Reload table, retry bounded; only then run_log `write_failed` |

That is implemented at `src/silver/table.py:187-203`: `OVERWRITE_MAX_ATTEMPTS =
3`, `OVERWRITE_BACKOFFS_S = (0.5, 1.0)`, catching `CommitFailedException`
specifically and re-raising on the last attempt. A transient infrastructure
failure is retried a bounded number of times with backoff, and only a failure
that survives that degrades the run.

The TTS row in the same table degrades on the first attempt. The two failures
are the same shape and get different treatment, and the difference does not look
deliberate.

This is not rule zero. Rule zero's validate-and-retry governs a model returning
output that fails its schema, and the caller feeds the error back into the next
prompt. A 503 is a transport failure with no output to validate and nothing to
feed back. It needs the `table.py` pattern, not the `call_validated` pattern,
which is why this needs a decision rather than reusing existing machinery.

### The bare `except Exception` is the actual blocker

A retry cannot be added responsibly on top of the current handler, because it
cannot tell what it caught. `tts.py:180` collapses a 503, a socket disconnect, a
read timeout, a missing API key, a malformed request, and a bug in the response
unpacking into one `TTSError`. Retrying the first three is the entire point.
Retrying a missing API key burns the step's time budget to arrive at the same
failure.

So the substance of this proposal is the split, not the loop:

- **Transient**, and retried: 503, 429, 500, 502, 504, connection and read
  timeouts, and server disconnects.
- **Permanent**, and failed immediately as today: authentication, invalid
  argument, an empty `pcm`, a missing `lameenc`, and anything unrecognized.

Unrecognized failures are treated as permanent deliberately. A new transient
error class costs one day's audio and shows up as a log line to classify, which
is the safe direction to be wrong in.

### The retry budget is bounded by the workflow, and it is tight

Four numbers constrain this and they interact.

| Bound | Value | Source |
| --- | --- | --- |
| Audio step ceiling | 15 min (900 s) | `.github/workflows/publish.yml:152` |
| Per-call TTS ceiling | 300 s | `config/pipeline.yaml:130` |
| A successful render at the publish window | median 188 s, max 303 s | 36 publish runs mined 2026-08-07 to 2026-09-14, see below |
| 2026-09-14's whole audio step | 6m04s | run 34828775022, 09:38:42 to 09:44:46 |

**The render time was measured rather than assumed**, because the assumption
turned out to be wrong. `config/pipeline.yaml:125-129` documented the 300 s
ceiling with "Normal renders finish inside two minutes; this is generous
headroom, not a target."

Two independent measurements say otherwise. A 1,508 word dialogue rendered
off-peak on 2026-09-14 took **214 seconds** and returned 442 seconds of audio.
More usefully, the Actions logs carry a render time for every publish since
2026-08-07, because a successful audio run logs its result line and the script
stage logs immediately before the render starts. Mining 36 of them:

| | Successful renders at the 09:35Z publish window |
| --- | --- |
| count | 26 of 36 days (10 failed) |
| wall clock | min 95 s, **median 188 s**, p90 254 s, **max 303 s** |
| normalized | 0.318 to 0.645 seconds of wall clock per second of audio, median 0.440 |
| TTS cost | $0.0620 to $0.1352 per edition, median $0.1021 |

**The ceiling sat inside that distribution rather than above it.** The slowest
successful render took 303.1 s. A render that failed with "The read operation
timed out" on 2026-08-31 took 301.6 s. Netting out the MP3 encode and the R2
upload, which these figures include, the slowest success had a TTS call within
roughly ten seconds of the ceiling and got its audio published by luck. Three
successful renders exceeded 250 s.

A timeout is supposed to catch a call that has stopped making progress. This
one was clipping the tail of ordinary renders, which is a different thing, and
it means **the 2026-09-14 timeout was most likely not an upstream stall at
all.** That is a second defect in the same config block and it is worth fixing
whichever way the retry decision goes.

Two further things the series settles, both of which were open questions this
document could not previously answer:

- **The publish window is not the problem.** The off-peak control, 0.484
  normalized, sits around the 75th percentile of the 09:35Z distribution.
  Renders at the publish hour are if anything slightly faster than off-peak, so
  "Google is busy at 09:35Z" is not the explanation.
- **The failure rate is getting worse.** August ran 4 failures in 23 days
  (17%). September ran 6 in 13 (46%). Same hour, same code, same model. The
  variable is time, not load, and the trend is the argument for acting now
  rather than waiting for #44's rework.

The failures split almost evenly between the two fixes, which is why this
document proposes both: five were fast-fails between 72 s and 263 s that a
retry very likely recovers, and five ran 288 s to 342 s against the ceiling.
Neither change alone addresses more than about half.

The arithmetic, using the measured render time and treating a timed-out attempt
as consuming the full 300 s:

| Shape | Worst case | Fits 900 s? |
| --- | --- | --- |
| One retry, second attempt succeeds | 60 + 300 + 30 + 214 = 604 s | yes, 5 min spare |
| One retry, both attempts time out | 60 + 300 + 30 + 300 = 690 s | yes |
| Two retries, all three time out | 60 + 300 + 30 + 300 + 30 + 300 = 1020 s | **no** |

**So one retry is free and two are not.** Two retries would require either
lowering `tts_timeout_seconds` to buy the room or raising the step ceiling, and
raising the step ceiling spends the publish's timeliness margin (section 8) on a
non-blocking stage, which is the wrong trade.

This proposal therefore asks for **one retry, with a fixed backoff of 30
seconds**, and deliberately does not ask for a general retry policy. The 503s in
the evidence fail in one to two minutes, so a second attempt at 30 seconds would
very likely have recovered 2026-09-12 and 2026-09-13 inside budget.

**There is room to raise the per-call ceiling at the same time.** At
`tts_timeout_seconds: 360.0` the worst case with one retry is
60 + 360 + 30 + 360 = 810 s, still inside the 900 s step ceiling. Given a typical
render of about 160 s, 360 s is genuine headroom where 300 s is not. Raising the
ceiling and adding the retry are complementary: the higher ceiling reduces how
often the timeout class fires at all, and the retry covers the capacity class
that no ceiling can help. Whether to move it is Milind's call and this proposal
does not fold it into decision #66.

**A timeout-class failure is the expensive one to retry** and is worth calling
out separately. Retrying it costs another full ceiling to probably fail again,
where a 503 costs ninety seconds to probably succeed. Treating them identically
is the simple design and this proposal takes it, but declining to retry the
timeout class, or giving the second attempt a shorter deadline than the first,
is a defensible alternative and it is Milind's call.

### Where the retry belongs, and why that matters for M8

**Inside the `Synthesizer` implementation, not in `run_audio`.**

SPEC 6.7 has already been rewritten for decision #44: single voice, one clip per
story, rendered lazily. The code has not, and the rework lands in M8. That makes
placement a real question rather than a stylistic one, because most of the
current audio orchestration is going to be replaced.

The retry belongs behind the swappable `Synthesizer` interface, which SPEC 6.7
keeps verbatim through the rework ("single-speaker TTS, Gemini behind a
swappable interface"). `run_audio.py`'s per-edition orchestration does not
survive. Putting the retry in the interface means M8 inherits it instead of
reimplementing it.

The rework changes the blast radius but does not remove the need. Post-M8 a
failed render costs one clip rather than the whole episode, and a lazily
rendered clip gets another chance on the next request. But SPEC 6.7 also says
the site's daily episode is "the concatenation of that edition's story clips"
and that the lead story and the top `general_score` stories are pre-rendered. So
TTS still runs during publish, and a transient failure there still costs the
daily episode. The retry is worth having on both sides of M8.

### Proposed SPEC 7 table row

Replacing the current `TTS fails | Publish without audio row; log`:

| Failure | Behavior |
| --- | --- |
| TTS fails, transient | Retry once after a fixed backoff, within the audio step's budget |
| TTS fails, permanent or after retry | Publish without audio row; log `audio_missing` |

### Proposed decision #66

> A transient TTS failure is retried once after a fixed backoff before the
> edition ships without audio, and the retry lives behind the `Synthesizer`
> interface rather than in the per-edition orchestration. Transient means the
> transport and availability classes, 503, 429, 500, 502, 504, timeouts and
> disconnects; everything else, including an unrecognized error, is permanent
> and fails immediately as it does today. The reason is that SPEC 7 already
> retries a transient infrastructure failure of exactly this shape in the silver
> commit race, while the TTS row degraded on first contact, and five of the six
> editions from 2026-09-09 to 2026-09-14 lost their audio to errors whose own
> messages said to try again later. One retry is the bound because the audio
> step's 15 minute ceiling and the 300 second per-call timeout leave room for a
> second attempt and not a third, and buying room for a third by raising the
> step ceiling would spend the publish's timeliness margin on a stage that is
> classed non-blocking. The split between transient and permanent is the
> substance: `tts.py`'s bare `except Exception` currently makes a missing API
> key and a 503 indistinguishable, and a retry loop over that would burn the
> budget re-attempting failures that cannot succeed. The placement is behind the
> `Synthesizer` interface because decision #44's rework replaces the per-edition
> orchestration and keeps the interface.

---

## Proposal B: sustained audio loss must surface

**Touches:** SPEC section 8 (observability), decision #27. Proposed new decision
**#67**.

### Four consecutive failures produced four correct log rows and zero signals

`REASON_AUDIO_MISSING = "audio_missing"` already exists at `src/runlog.py:62`,
is in the `REASONS` frozenset, and was written on every one of these runs. The
observability worked. Nothing consumed it.

`DEGRADED_REASONS` holds exactly `editor_invalid_fallback` and
`assembly_fallback`. `audio_missing` is deliberately not in it, and that is
correct under decision #27: degraded means readers got a fallback link-list
where a real edition was possible, and a normal edition without audio is not
that. The audio step is `continue-on-error: true` precisely so it never reddens
a publish.

So every mechanism behaved correctly and the outcome was still that the feature
was dead for four days and the way it was discovered was someone noticing.

### The gap is the missing distinction between a miss and a streak

One edition without audio is acceptable and by design. Four consecutive is a
broken feature. Nothing in section 8 distinguishes them, because every existing
signal is per-run: healthchecks is published-or-not for one day, the degraded
check reddens one run, the run log records one row.

Section 8 already contains the precedent for a cross-run signal. The external
trigger row in SPEC 7 resolves to "surfaced as sustained lateness (section 8),
never as a missed day". Sustained lateness is a property of a window of runs,
not of one. Sustained audio loss is the same kind of property and has no
equivalent.

### What this proposal asks for, and what it leaves open

A threshold signal over consecutive publish runs carrying `audio_missing`, at
the same volume as the degraded-publication signal: it reddens an Actions run
after a successful deploy, and it never touches healthchecks, which stays a pure
published-or-not signal for the page.

`src/degraded_check.py` is the natural home, since it already performs a
post-deploy query over the run log and reddens the workflow on the answer. This
proposal does not specify whether it extends that script or gets a sibling.

**The threshold itself is deliberately left to Milind.** Two is arguably too
noisy given that single misses are expected and acceptable. Three would have
fired on 2026-09-13 and caught this a day before it was noticed. The evidence
supports three and does not prove it.

**This must not be folded into `DEGRADED_REASONS`.** The word "degraded" has a
precise meaning in decision #27 and section 8, it drives the existing alert, and
a normal edition without audio genuinely is not it. This is a second signal that
happens to share a delivery mechanism, not a widening of the first. Widening
degraded would make a real definition fuzzy to save writing a query.

### The reader-visible consequence, for weighing the threshold

`site/src/pages/feed.xml.ts:60` emits no `<enclosure>` and no
`<itunes:duration>` when `audio` is null, which is correct and keeps the feed
valid. What a podcast subscriber saw over the last four days is four consecutive
episodes with nothing to play. The site page is fine and simply shows no player.
The feed is where sustained loss is felt, which is an argument for a threshold
low enough to catch a streak while it is still short.

### Proposed decision #67

> Sustained audio loss is surfaced as a threshold over consecutive publish runs
> carrying `audio_missing`, reddening an Actions run after a successful deploy in
> the same way a degraded publication does, and never touching healthchecks. It
> is not added to `DEGRADED_REASONS`. The reason is that a single edition
> without audio is correct behavior under SPEC 7 while four consecutive is a
> broken feature, and section 8 had no signal that could tell them apart: from
> 2026-09-09 to 2026-09-14 the run log recorded `audio_missing` faithfully every
> time and nothing consumed it, so the outage was found by a person noticing
> rather than by the system. The signal is kept out of the degraded subset
> because decision #27 gives "degraded" the specific meaning of a fallback
> link-list published where a real edition was possible, which a normal edition
> without audio is not, and widening that definition to reuse its alert would
> cost the precision the definition exists to provide. This follows the existing
> treatment of sustained lateness, which is likewise a property of a window of
> runs rather than of one. The same row records the TTS render's wall-clock
> duration, because the 300 second ceiling was set on an estimate that measured
> wrong by roughly a factor of two and nothing in the system recorded the number
> that would have caught it.

---

## Proposal C: record the render latency

**Touches:** SPEC section 8 (observability). Folded into proposed decision
**#67** rather than given its own number, because it is the same argument:
audio failures are invisible until something records them.

The 300 s ceiling was set on the estimate that "normal renders finish inside
two minutes." Measuring it took one afternoon and the estimate was wrong by
roughly a factor of two. Nobody had measured it because nothing records it.

The audio `run_log` row carries `ai_cost_estimate_usd` but no timing. Adding the
TTS render's wall-clock duration to that row makes the timeout a question that
can be answered from data on the next occasion rather than re-derived by hand.
It is one field, it is deterministic, it costs nothing to collect, and it is
what turns "the ceiling seems too tight" into a distribution.

It also directly serves the migration question deferred below. A latency series
across the 09:35Z publish window is the evidence that would distinguish "this
model is undersupplied at our publish hour" from "this model is undersupplied
generally," and neither the retry nor a model swap should be evaluated without
it.

## Proposed addition to section 11

Under the non-app-layer questions:

- Which text-to-speech model the audio build should pin. Deferred to **M8**,
  where decision #44's rework already reopens the audio stage. As of 2026-09-14
  no GA text-to-speech model exists to move to: every candidate is preview or
  experimental, so the preview label on the current model is not by itself the
  defect. The measured comparison on that date, on a 1,508 word script:
  `gemini-2.5-flash-preview-tts` rendered in 214 s for $0.1116, and
  `gemini-3.1-flash-tts-preview` rendered in 190 s for $0.2961, the latter being
  twice the per-token price and emitting a third more output tokens. 3.1 is a
  verified drop-in for both the current multi-speaker call and the single-voice
  call #44 moves to, and it supports `batchGenerateContent` at half price, which
  suits 6.7's pre-rendering. The reason to defer rather than decide now is that
  a 2.65x cost increase buys an 11% latency gain and no reliability guarantee,
  since both models are preview with no SLA, while the retry in decision #66
  helps whichever model is pinned. Revisit when #44's rework lands and the
  latency series from proposal C exists. See proposal C.

## A note on decision numbering

SPEC section 10's decision log ends at **#56**. Three unapproved proposal
documents already claim numbers past it, and two of them collide:
`PROPOSED-SPEC-edition-durability.md` claims #57 and #58, while
`landing/PROPOSED-SPEC-DISCOVERY.md` claims #57 through #61 and
`landing/PROPOSED-SPEC-BLOG.md` chains off it with #62 through #65.

This document claims **#66 and #67** to sit clear of all of them. The numbers in
every one of these documents are provisional until approval decides the order,
and the edition-durability collision needs resolving whichever way that goes.
Flagging it here rather than renumbering anything unilaterally.

## What is deliberately absent

- **No code.** Both proposals wait for approval under rule 1.
- **No change to SPEC 7's guarantee that a TTS failure never blocks a publish.**
  Both proposals keep the audio build non-blocking. A retry that survives its
  bound still ships the edition without audio.
- **No change to the healthchecks contract.** It stays published-or-not.
- **Nothing touching the app path.** SPEC 14 is unaffected. The per-user path
  has no TTS stage today, and 6.7's per-story clips are shared by both paths, so
  neither proposal introduces per-user work.
- **No retry on the script stage.** It already has two attempts and did not fail
  in any of these runs. The off-band word-count warnings in the logs are a soft
  target, not a failure, and the render proceeded in every case.
- **No claim that one retry is sufficient.** It is what the step's time budget
  affords without other changes. If audio loss continues at this rate after a
  retry lands, the next question is the model or the budget, not a third
  attempt.
