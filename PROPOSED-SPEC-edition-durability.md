# Proposed spec addition: edition durability

**Status: a proposal. It governs nothing.** Under CLAUDE.md rule 1 these two
changes need a spec addition approved before the code that implements them.
Nothing here has been implemented. Where this document disagrees with SPEC.md,
SPEC.md wins.

This exists because three consecutive publish days went wrong in three
different ways, and two of them cost an edition that did not have to be lost.

| Date | What happened |
| --- | --- |
| 2026-08-25 | The editor placed one cluster in two sections. The `Edition` validator rejected the whole edition. Fallback published. |
| 2026-08-26 09:36 | The editor **succeeded**. A real edition was built. The Gemini TTS call then hung, the job died at GitHub's 6 hour ceiling, and the edition was never committed. **Nothing published.** |
| 2026-08-26 16:25 | Re-run. The editor named a cluster that was never offered. Assembly raised. Fallback published, late and degraded. |

PR #43 has already landed the mechanical half of the middle row: the TTS call
and the audio step are bounded, so a hang cannot burn six hours again. It did
not address why the hang cost the edition, and it fixed only one of the two
editor slips. Those two remainders are proposals A and B.

**The two proposals are independent.** They share a premise and a week of
evidence, which is why they are in one document, but either can be approved
without the other.

---

## Proposal A: commit the edition before the audio build

**Touches:** SPEC 6.8 (step order), SPEC 7 (the unpublished-day enumeration),
decision #17. Proposed new decision **#57**.

### This is not a new policy, it is an enforcement gap

The spec already forbids what happened on 2026-08-26, in three places.

SPEC section 7, on non-blocking stages:

> A stage the publish workflow classes as non-blocking, the audio build being
> the one such stage today, must never fail the workflow. A non-zero exit from
> it publishes the edition without that stage's contribution (SPEC 7's "publish
> without audio row"), rather than **stranding an edition that is already
> built**.

Decision #26:

> A stage that has not yet produced an edition degrades to the fallback; a
> stage that already holds a valid one publishes it unrevised. **Enforced at
> the orchestration points** rather than at each failure site, so a future
> required field on the edition schema can cost quality but never the day.

SPEC section 7, closing the failure discussion:

> Exactly two conditions still leave a day unpublished: no candidate contexts
> at all, and a failure to write the file itself.

On 2026-08-26 the edition was built, validated, and written to the runner's
filesystem. Neither of those two conditions held, and the day went unpublished
anyway. That is a third condition the spec says does not exist, and SPEC 6.8's
step order is what makes it reachable.

### Why the existing containment cannot deliver the guarantee

`continue-on-error: true` on the audio step was the previous attempt at
decision #26's promise, and it is structurally incapable of keeping it. It
contains a step that **fails**. It does nothing for a step that never
**finishes**, because the step never reports a result for the flag to act on.

`timeout-minutes`, merged in PR #43, converts a hang into a failure and so
brings the hang back inside `continue-on-error`'s reach. It still loses the
edition, because `Commit edition` is downstream of `Audio build` either way. It
bounds the damage from six hours to fifteen minutes without changing the
outcome for the day.

The ordering, not the flag, is the thing that decides whether a built edition
survives.

### The proposed amendment

SPEC 6.8's numbered steps become, in order: build the edition, **commit it**,
build audio, **commit the injected audio block**, then Astro build, deploy,
ping, archive.

The rule the amendment states: **an edition is committed as soon as it
validates, before any non-blocking stage runs.** A non-blocking stage may cost
its own contribution and may never cost the edition.

### What this costs, stated plainly

Decision #17 makes the committed edition the publication record, and this makes
a date's record potentially **two commits rather than one**. That is the part
that genuinely needs a decision rather than a patch, and it is the reason this
document exists instead of a pull request.

Two observations that reduce the cost, offered as argument and not as a way
around the decision:

- "One commit per date" is not an invariant the repo currently holds. A
  same-day re-run already produces additional commits against the same date,
  and the 2026-08-26 recovery produced one today.
- The record's *content* is unchanged. The same `edition.json` reaches the same
  path with the same bytes; only the number of commits that got it there
  differs.

**Verified:** neither `publish.yml` nor `collect.yml` triggers on `push`. Both
are `schedule` plus `workflow_dispatch` only. A second commit therefore cannot
re-trigger the publish workflow, so the obvious objection to a two-commit
design does not apply.

### Proposed decision #57

> The edition is committed as soon as it validates, before the audio build,
> and the audio block is committed separately after injection. A date's
> publication record is therefore one or two commits rather than exactly one.
> The reason is that decision #26 and section 7 both already promise that a
> stage which already holds a valid edition publishes it, and that a
> non-blocking stage never strands an edition that is already built, while
> 6.8's step order placed the commit downstream of the one stage classed as
> non-blocking. On 2026-08-26 that ordering left a validated edition on a
> destroyed runner and produced the empty day section 7 says is reachable by
> exactly two causes, neither of which had occurred. `continue-on-error` cannot
> close this because it contains a step that fails and not one that hangs, and
> `timeout-minutes` only converts the hang into the failure case while leaving
> the commit downstream. Committing twice is the smaller cost: the record's
> content is unchanged, same-day re-runs already produce more than one commit
> per date, and neither workflow triggers on push so the second commit starts
> nothing.

---

## Proposal B: validate the editor's cluster ids on the response, not the edition

**Touches:** SPEC 6.5, SPEC 7's failure table, section 8's reason codes,
decisions #25, #26, #27. Proposed new decision **#58**.

### The same slip is contained in one place and fatal in another

Both of these are in `src/editor/assemble.py`, roughly a hundred lines apart.

`_briefly_items`, on resolving the editor's briefly ids:

> Ids that are unknown, that name a story already placed in a section, or that
> carry no section topic are dropped.

The section path, on the identical mistake:

```python
context = by_id.get(story.cluster_id)
if context is None:
    raise _invalid(
        f"editor selected cluster {story.cluster_id!r} which was not offered"
    )
```

An id the editor invented is silently absorbed if it lands in briefly and costs
the entire edition if it lands in a section. On 2026-08-26 it landed in a
section.

### Decision #25 already settled the principle

Decision #25 decided this exact question for a different field:

> Enforced on the editor response, never on the assembled edition, **because a
> rejected response is retryable while a rejected edition degrades to a
> fallback**.

The offered-cluster constraint is checkable on the response: the set of offered
ids is `contexts`, which `run_editor` already receives. By #25's own reasoning,
that is where the check belongs. Enforcing it on the assembled edition converts
a retryable model slip into a lost day, which is precisely the trade #25
rejected.

### The proposed two-layer design

**Layer 1, a retryable check on the response.** `EditorResponse` is a plain
Pydantic model with no access to the offered ids, so the check cannot live on
the model. It belongs in `llm.call_validated` as an optional `post_validate`
callable, invoked inside the existing `try` block immediately after the
response is parsed. Anything raised there is already caught, recorded as
`last_error`, and fed back to the model on the retry. A domain check therefore
inherits rule zero's validate-and-retry behavior with no new retry machinery,
and `run_editor` supplies the closure that knows the offered ids.

**Layer 2, containment in assembly as the backstop.** If an unknown id still
arrives after the retry, drop that story exactly as `_briefly_items` already
drops one, rather than raising. This makes assembly's own stated contract true.

Order matters here for the same reason it mattered in the merged dedup fix: the
drop must happen before the per-section story budget is measured, so a section
left short by a dropped story collapses into briefly like any other short
section instead of failing a different validator.

### Audit of the remaining fatal paths

`assemble_edition` has **exactly one** hard raise, the one quoted above, plus
the closing `validate_edition(edition)` call. With the merged duplicate-cluster
fix and proposal B, every known path by which an editor slip reaches the schema
validator and degrades the day is closed. The audit is small and its result is
reassuring, which is worth stating because it was previously described as an
open question.

### Proposed SPEC 7 table row

| Failure | Behavior |
| --- | --- |
| Editor names a cluster not offered | Retry once with the error; then drop the story. Never a fallback |

### The counter-argument

A fallback is a loud signal and a drop is quiet. If the editor begins inventing
ids frequently, containment hides the regression rather than surfacing it.

Section 8 already has the mechanism for this. The drop records an enumerated
`run_log` reason code rather than passing silently, following the convention in
`src/runlog.py`: `REASON_CLUSTER_NOT_OFFERED = "cluster_not_offered"`, added to
the `REASONS` frozenset, which `shape_row` validates against so an unknown code
raises rather than being written.

**Whether that code joins the degraded subset is a decision for Milind, and
this proposal deliberately does not make it.** `DEGRADED_REASONS` currently
holds exactly `editor_invalid_fallback` and `assembly_fallback`.

One consequence should be weighed when deciding. The red Actions run on
2026-08-26 came from `assembly_fallback`, which is in the degraded subset. If
proposal B lands, this path stops producing a fallback at all, so it stops
being degraded as a side effect of the fix. That is exactly why the new reason
code is needed regardless of the degraded question: without it, a slip that is
currently loud becomes invisible rather than merely non-degraded.

### Proposed decision #58

> The editor's cluster ids are validated against the offered set on the editor
> response, where a failure is retryable, and never on the assembled edition,
> where it degrades the day. An id that survives the retry is dropped in
> assembly and recorded as `cluster_not_offered` in `run_log.reasons`. This
> applies decision #25's reasoning to a second field rather than introducing a
> new principle, and it resolves an inconsistency in which the same invented id
> was silently dropped from briefly and fatal in a section. The drop is
> recorded rather than silent because containment would otherwise hide a
> regression in the editor, and because this path currently reports itself as
> degraded through `assembly_fallback`, which the fix removes.

---

## What is deliberately absent

- **No code.** Both proposals wait for approval under rule 1.
- **No change to the fallback edition, decision #8, or decision #26's
  guarantee.** Both proposals make #26 more true, not less.
- **Nothing touching the app path.** SPEC 14 is unaffected; both are site-path
  only.
- **No claim that the TTS timeout is proven.** PR #43's `tts_timeout_seconds`
  has not executed in production, because a fallback edition carries no audio
  and 2026-08-26 published a fallback. The first real exercise is the next
  publish that produces a normal edition. This is an open verification item,
  not a fix to rely on yet.
