# trigger-worker

The external publish trigger (SPEC 6.11, decision #31). A Cloudflare Worker
that calls this repo's `workflow_dispatch` endpoint three times a morning so
the publish starts on time instead of whenever GitHub's scheduler gets to it.

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
(`Metadata: Read-only` is added automatically and cannot be removed.)

Deliberately not `Contents: write`, which is what GitHub requires for the
repository-dispatch endpoint. That permission would also let this token commit
code, delete files and cut releases. This token lives outside GitHub and the
workflow it starts runs with every other secret in the project, so it gets the
narrowest thing that can start a workflow and nothing more (SPEC 6.11).

Set the longest expiry GitHub offers. Check what that maximum currently is when
you create it, since the policy has changed before. Write the expiry date into
SETUP.md, because an expired token fails silently: the dispatch 401s, GitHub's
crons still publish, and the only symptom is that mornings quietly get late
again.

**2. Verify the token works** before deploying anything:

```bash
GITHUB_TRIGGER_TOKEN=github_pat_... uv run python spikes/check_dispatch.py
```

That sends a real dispatch. It is safe: it does not set `force`, so the gate
no-ops it unless the window is open and today is unpublished.

**3. Open the Workers section of the Cloudflare dashboard once**, at
https://dash.cloudflare.com/<account-id>/workers/workers-and-pages

Do not create anything. Loading the page is enough. It registers the account's
workers.dev subdomain, which a brand new Cloudflare account does not have.

This step looks skippable and is not. Without it, the script uploads fine and
the secret attaches fine, and then setting the cron schedules fails with a bare
`403` that names no cause. The real error only appears if you query the API
directly:

```
code 10007: You do not have a workers.dev subdomain.
```

If wrangler offers to register the subdomain during `deploy`, saying yes does
the same job. Saying no leaves you with a deployed Worker that never fires,
which is what happened the first time this was set up on 2026-07-27.

Registering the subdomain does **not** give this Worker a public address.
That is `workers_dev = false` in `wrangler.toml`, a per-Worker setting. The
subdomain is account-level. You need the account one; you do not want the
Worker one.

**4. Deploy.**

```bash
cd ops/trigger-worker
npx wrangler login
npx wrangler secret put GITHUB_TOKEN     # paste the token, it is never in a file
npx wrangler deploy
```

The deploy must end with three `schedule:` lines. If it says
`No targets deployed`, the code shipped but the alarm did not, and the Worker
will never run. Confirm from Cloudflare's side rather than the CLI:

```bash
npx wrangler triggers deploy    # re-runs just the schedules
```

## Checking it works

The morning after deploying, the site should be live before 06:00 ET and the
run should record `trigger=worker`. Both are visible in one place:

```bash
uv run python -m src.timeliness --since 2026-07-28
```

`trigger` should read `worker` and the verdict `on time`. If it reads
`schedule`, the Worker is not reaching GitHub and the cron is still doing the
work. If it reads `manual`, something dispatched without the `source` input.

The Worker uses the same `workflow_dispatch` event a human does, which is the
price of the narrower token, so that `source` input is the only thing
distinguishing them.

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
