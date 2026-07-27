# trigger-worker

The external publish trigger (SPEC 6.11, decision #31). A Cloudflare Worker
that POSTs a `repository_dispatch` to this repo three times a morning so the
publish starts on time instead of whenever GitHub's scheduler gets to it.

This is deployment infrastructure, not pipeline code. It is never imported by
`src/`, and pytest does not collect it (`testpaths = ["tests"]`).

## Why it exists

GitHub's scheduled events were created 82 to 192 minutes after their target on
every day measured from 2026-07-21 to 2026-07-27. Publication landed 07:15 to
08:52 ET against SPEC 6.8's 06:00 goal, which had therefore never once been
met. Cloudflare's scheduler is a second, independent one. Both stay wired up:
the publish gate makes whichever trigger arrives second a harmless no-op, so
the redundancy is free.

## The one rule

**This Worker carries no logic.** No DST handling, no "did we already publish
today", no retries with conditions. One POST per firing. Every decision belongs
to `src/schedule.py`, where the tests pin it, and the workflow gate applies it
to all triggers identically.

If you ever find yourself wanting to add an `if` here, the answer is almost
certainly that the gate should handle it instead.

## First deploy

You need a Cloudflare account (the one already holding R2 is right) and a
GitHub token.

**1. Create the token.** A fine-grained personal access token, scoped to this
repository only, with exactly one permission: `Actions: read and write`.

Set the longest expiry GitHub offers. Check what that maximum currently is when
you create it, since the policy has changed before. Write the expiry date into
SETUP.md, because an expired token fails silently: the dispatch 401s, GitHub's
crons still publish, and the only symptom is that mornings quietly get late
again.

**2. Verify the token works** before deploying anything:

```bash
GITHUB_TRIGGER_TOKEN=github_pat_... uv run python spikes/check_dispatch.py
```

That sends a real dispatch. It is safe: the gate will no-op it unless the
window is open and today is unpublished.

**3. Deploy.**

```bash
cd ops/trigger-worker
npx wrangler login
npx wrangler secret put GITHUB_TOKEN     # paste the token, it is never in a file
npx wrangler deploy
```

## Checking it works

The morning after deploying, the publish run should show
`event_name: repository_dispatch` and the site should be live before 06:00 ET.
Both are visible in one place:

```bash
uv run python -m src.timeliness --since 2026-07-28
```

`trigger` should read `repository_dispatch` and the verdict `on time`. If it
reads `schedule`, the Worker is not reaching GitHub and the cron is still doing
the work.

Cloudflare's own view:

```bash
npx wrangler tail                 # live logs
npx wrangler deployments list
```

## When it breaks

The failure modes are an expired token (401), a repo that moved (404), and
Cloudflare or GitHub being down. None of them lose an edition: GitHub's crons
still publish, just late.

That is deliberate, and it is why nothing here pings healthchecks. Healthchecks
answers one question, "did the site publish," and SPEC section 8 keeps it that
way. A dead Worker has not stopped the site publishing, so it must not turn
that check red. Sustained lateness in the timeliness report is the signal
instead.

## After the migration

SPEC 13 step 4b. The repo owner and name both change, and the fine-grained
token dies with them, so the Worker needs `GITHUB_OWNER` and `GITHUB_REPO`
updated in `wrangler.toml`, a fresh token, and fine-grained PAT access enabled
in the new organization's settings (an org-level policy that the repo transfer
does not carry).

Verify with the spike before running the migration's publish cycle. The
migration's exit criterion requires a publish that was dispatch-triggered,
precisely because a broken Worker is otherwise invisible behind a working cron.
