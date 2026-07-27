// The external publish trigger (SPEC 6.11, decision #31).
//
// GitHub's scheduled events were created 82 to 192 minutes after their target
// on every measured day from 2026-07-21 to 2026-07-27, so the publish landed
// 07:15 to 08:52 ET against a 06:00 goal. This Worker fires on Cloudflare's
// scheduler instead, 5 minutes after the publish window opens, and asks GitHub
// to run the workflow now.
//
// This file carries NO logic on purpose. It does not know about daylight
// saving, it does not know whether today already published, and it must never
// learn. Those decisions live in src/schedule.py, where the tests pin them,
// and the workflow's gate applies them to every trigger identically. A second
// copy of the scheduling rules living here in JavaScript is exactly the
// failure this design exists to avoid.
//
// So: three cron firings a day, one POST each, no conditionals. The gate makes
// the firings that should do nothing do nothing.

const API = "https://api.github.com";

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatch(env));
  },
};

async function dispatch(env) {
  // Owner, repo, workflow and ref come from wrangler.toml vars rather than
  // being written in here, because the SPEC 13 migration changes them. Step 4b
  // is then a config edit, not a code edit.
  //
  // The workflow dispatch endpoint, not the repository dispatch one. The
  // latter is granted under `Contents: write`, which would also let this token
  // commit code; this one needs only `Actions: write` (SPEC 6.11).
  const url =
    `${API}/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}` +
    `/actions/workflows/${env.WORKFLOW_FILE}/dispatches`;

  const response = await fetch(url, {
    method: "POST",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "X-GitHub-Api-Version": "2022-11-28",
      // GitHub rejects API requests without one.
      "User-Agent": "norms-newsletter-trigger",
    },
    // `source` is what distinguishes this from a human pressing the button,
    // which is how a dead Worker becomes visible. `force` is deliberately not
    // sent: the workflow's declared default is false, and this trigger must
    // never bypass the publish gate.
    body: JSON.stringify({
      ref: env.GIT_REF,
      inputs: { source: "worker" },
    }),
  });

  // A successful dispatch is 204 No Content.
  if (response.ok) {
    console.log(`dispatched publish (${response.status})`);
    return;
  }

  // Logged, not retried and not escalated. The failure modes here are an
  // expired token (401), a repo that moved (404), and GitHub being down, none
  // of which this Worker can fix. Publication is not lost: GitHub's own crons
  // still run the workflow, just late. That is precisely why SPEC section 8
  // makes sustained lateness the health signal for this Worker rather than
  // wiring it into healthchecks, which stays a pure published-or-not signal.
  const body = await response.text();
  console.error(`dispatch failed: ${response.status} ${body}`);
}
