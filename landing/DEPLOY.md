# Deploying the landing page to norm.news

A start-to-finish guide for putting `landing/` on `norm.news`. Written to be
followed by someone who has never touched DNS. Roughly 30 minutes of work plus
some waiting.

**This does not touch the site.** The Astro newsletter in `site/` keeps
publishing to GitHub Pages exactly as it does today. `astro.config.mjs` is not
edited here. See SPEC section 13 for where the site goes at launch.

## First, the mental model

Three separate things are involved, and mixing them up is the main reason this
gets confusing. They are owned by different systems and you configure them in
different places.

| Thing | Who does it | What it means |
| --- | --- | --- |
| **Registrar** | Porkbun | The shop you bought the name from. After the sale its only real job is to record *who is allowed to answer questions about this domain*. |
| **Nameservers (DNS)** | Porkbun today, Cloudflare after step 1 | The phone book. When a browser wants `norm.news`, it asks the nameservers "where do I actually go?" |
| **Host** | Cloudflare Pages | The computer that holds `index.html`, `og.png` and the rest, and hands them to the browser. |

So the job is: **tell Porkbun to let Cloudflare answer for the domain, put the
files on Cloudflare Pages, then tell Cloudflare to connect the two.**

### Why the nameservers have to move

You might reasonably ask why we cannot leave DNS at Porkbun and just point a
record at Cloudflare. For `www.norm.news` you could. For the bare `norm.news`
you cannot, and it is worth understanding why, because the error you get
otherwise is unhelpful.

Pointing one name at another name is a DNS record type called `CNAME`. The DNS
standard does not permit a `CNAME` on a bare domain, only on subdomains. So
`norm.news → norm-news.pages.dev` is not a legal record. Providers work around
this with a non-standard trick (usually called CNAME flattening: they resolve the
target themselves and hand back the resulting IP address), and only the provider
answering for the domain can do that trick.

Cloudflare does it automatically, but only for domains it is the nameserver for.
Cloudflare's own documentation states the requirement plainly: to use an apex
domain with Pages, that domain must be a zone on the same Cloudflare account.
So the move is mandatory, not a preference.

## Before you start

You need:

- The Porkbun login for the account that owns `norm.news`
- The Cloudflare login for the account that already runs
  `norms-newsletter-trigger` (see `ops/trigger-worker/README.md`). Use the same
  account. The Pages project and the domain must live together.
- Node installed, and this repo checked out
- `npm install` already run in **both** `landing/` and `site/`. The landing page
  borrows its image-rendering tools from `site/node_modules`.

Sanity check before you touch anything:

```bash
cd landing
npm run og      # regenerates og.png and apple-touch-icon.png
npm run build   # writes dist/
ls dist/index.html dist/og.png dist/favicon.svg dist/apple-touch-icon.png
```

All four files must exist. If they do not, stop and fix that first. Deploying a
build that is missing its assets just moves the problem somewhere harder to see.

---

## Step 1. Hand DNS to Cloudflare

### 1a. Check DNSSEC at Porkbun first

Do this before anything else. **DNSSEC is a signature system that proves DNS
answers have not been tampered with.** If it is switched on and you change
nameservers without switching it off, the signatures no longer match the new
answers and every resolver on the internet will refuse to resolve the domain at
all. The site does not just fail, it becomes unreachable in a way that looks
nothing like a configuration mistake.

In Porkbun: **Domain Management** → find `norm.news` → **Details** drop-down →
look for a DNSSEC section. If it lists any records, delete them. On a
freshly bought domain it is almost always already empty. You can turn DNSSEC
back on from the Cloudflare side later once everything works.

### 1b. Add the domain to Cloudflare

1. Log in to the Cloudflare dashboard
2. **Add a domain** (older UI: **Add site**)
3. Type `norm.news`, continue
4. Choose the **Free** plan. Nothing here needs a paid plan.
5. Cloudflare scans for existing DNS records and shows you a **Review your DNS
   records** screen. **Delete everything it found**, then continue. See below
   for why.
6. Now Cloudflare shows you **two nameservers**. They look like
   `alice.ns.cloudflare.com` and `bob.ns.cloudflare.com`, with random first
   words specific to your account. **Copy both exactly.** These are the only
   thing on any of these screens that you need to copy.

#### Deleting the records Cloudflare found

A freshly bought Porkbun domain is not empty. Porkbun pre-creates records for a
"this domain is parked" placeholder page, so expect roughly:

| Type | Name | Points at |
| --- | --- | --- |
| `A` | `norm.news` | a Porkbun parking IP, e.g. `207.207.210.36` |
| `A` | `norm.news` | a second Porkbun parking IP |
| `CNAME` | `www` | `uixie.porkbun.com`, the parking host |
| `CNAME` | `*` | the same parking host, for every possible subdomain |
| `TXT` | `_acme-challenge...` | Porkbun proving ownership to get a cert for that page |

You can confirm the A records are the parking page rather than anything of yours:

```bash
dig +short uixie.porkbun.com   # returns the same IPs as the A records
```

Delete all of them. The `A` records on the bare domain and the `CNAME` on `www`
are the ones that genuinely matter, because they sit on exactly the two names you
attach to Pages in step 3. Cloudflare has to create its own records there, and
Porkbun's leftovers either block that or produce a **522** on a domain that looks
correctly configured.

The `*` wildcard is worth deleting on principle: it is a catch-all, so every
subdomain you never set up still resolves to Porkbun's page.

The `_acme-challenge` TXT records are harmless, just useless once the parking
page is gone. If the row only offers **Edit** and no delete, leave them and tidy
up later from the DNS tab.

Ignore the **Proxied / DNS only** toggles on this screen. Pages sets that itself
for the records it creates in step 3.

### 1c. Point Porkbun at them

In Porkbun: **Domain Management** → find `norm.news` → **Details** drop-down →
find the **Nameservers** field → click the **edit icon**.

1. Delete all the existing entries. There are usually four, ending in
   `.ns.porkbun.com`.
2. Add the two Cloudflare nameservers, **one per line**
3. **Save Nameservers**, then **Submit** in the confirmation dialog

Then go back to Cloudflare and click **Check nameservers**.

**This step is not instant.** It usually completes in 15 to 60 minutes, and
Porkbun warns it can take up to 48 hours. Cloudflare emails you when the domain
is active. You do not have to wait idle: step 2 works right now and does not
depend on DNS at all.

Check progress from your terminal:

```bash
dig +short NS norm.news
```

You are done with this step when that prints the two `.ns.cloudflare.com`
names instead of the Porkbun ones. Until then it prints the old ones, which is
normal and not a sign anything is broken.

> One consequence to be aware of: once nameservers move, any DNS records you had
> at Porkbun stop being used. On a new domain with no email set up there is
> nothing to lose. If you ever add email on this domain, its MX records go in
> Cloudflare from now on, not Porkbun.

---

## Step 2. Put the files on Cloudflare Pages

You can do this while step 1 is still propagating.

### 2a. Log in to Cloudflare from the terminal

```bash
cd landing
npx wrangler login
```

This opens a browser to authorize. Confirm you landed in the right account:

```bash
npx wrangler whoami
```

If it shows the wrong account, run `npx wrangler logout` and log in again. A
Pages project in one account cannot serve a domain in another, and the failure
message when you get this wrong does not point at the cause.

### 2b. Create the project

```bash
npx wrangler pages project create norm-news --production-branch main
```

The name `norm-news` becomes part of a free URL, `norm-news.pages.dev`, which
stays working forever alongside the real domain. It is useful for testing, so do
not treat it as throwaway.

### 2c. Deploy

```bash
npm run build
npx wrangler pages deploy dist --project-name norm-news --branch main --commit-dirty=true
```

Both flags matter, and neither is optional.

**`--branch main` is what makes this a production deployment.** Pages sorts every
deployment into production or preview by comparing its branch against the
project's production branch, set to `main` in step 2b. If you leave the flag off,
Wrangler reads the branch from git, and on any branch other than `main` the
deployment is filed as a **preview**. Previews are real and reachable, but
`norm-news.pages.dev` and every custom domain serve the **production**
deployment only. So a preview-only project has a working `pages.dev` hash URL, a
working branch URL, and a dead `norm-news.pages.dev`, and later a `norm.news`
that resolves and certifies correctly while serving nothing.

Passing `--branch main` while checked out on a feature branch is normal here.
This is a direct upload, so there is no git integration; `--branch` is just a
label Pages uses to choose the environment.

**`--commit-dirty=true`** tells Wrangler you know the git working tree has
uncommitted changes and to deploy anyway. Without it, Wrangler stops and asks.

Neither flag changes what gets uploaded: **the contents of `dist/` are what ship,
and git state is only metadata.** A deployment can contain changes you never
committed, and can be labelled `main` while built from another branch. Build from
a clean tree when you care about reproducing what is live.

### 2d. Check it before involving the domain

First confirm the deployment is production, not preview:

```bash
npx wrangler pages deployment list --project-name norm-news
```

The Environment column must say **Production**. If it says Preview, redo 2c with
`--branch main`.

Then open `https://norm-news.pages.dev` and confirm:

- The page loads and the hero reads "Read less. Miss nothing."
- The mug appears as the tab icon
- Nothing in the browser console is red (Chrome: **View → Developer → JavaScript Console**)

Get this working before step 3. If the page is broken here, it will be broken on
`norm.news` too, and you will not be able to tell whether you are looking at a
DNS problem or a build problem.

---

## Step 3. Connect the domain

Both step 1 and step 2 must be finished. Cloudflare must show `norm.news` as
**Active**, and `norm-news.pages.dev` must work.

1. Cloudflare dashboard → **Workers & Pages** → the **norm-news** project
2. **Custom domains** tab → **Set up a domain**
3. Enter `norm.news`, continue, confirm
4. Repeat for `www.norm.news`

There is no CLI for this. Cloudflare only supports it through the dashboard, so
the clicking is unavoidable.

Cloudflare now writes the DNS records itself and issues an HTTPS certificate.
Expect a few minutes; the status moves through "Initializing" to "Active".

> **Do not hand-write a DNS record to shortcut this.** It is tempting, since you
> can see what record is needed. But Pages also has to be told internally which
> project answers for which hostname, and only the Custom domains flow does that.
> A hand-made record produces a **522 error** on a domain that looks correctly
> configured, which is a genuinely difficult thing to debug. Let Cloudflare
> create the record.

---

## Step 4. Send www to the bare domain

After step 3, `norm.news` and `www.norm.news` both serve the page independently.
That is two addresses with identical content, which splits search ranking and
makes analytics harder to read. Pick one as canonical, and `index.html` already
declares `https://norm.news/`, so `www` should redirect to it.

1. Cloudflare dashboard → select the **norm.news** domain (not the Pages
   project) → **Rules** → **Redirect Rules** → **Create rule**
2. Name: `www to apex`
3. Under **If incoming requests match**, choose **Custom filter expression**:
   - Field **Hostname**, Operator **equals**, Value `www.norm.news`
4. Under **Then**:
   - Type: **Dynamic**
   - Expression: `concat("https://norm.news", http.request.uri.path)`
   - Status code: **301**
   - Tick **Preserve query string**
5. **Deploy**

`Dynamic` with that expression is what preserves the path, so
`www.norm.news/about` lands on `norm.news/about` rather than the homepage. A
static redirect would send every URL to the root.

---

## Step 5. Verify

```bash
# The domain resolves and is served by Cloudflare
dig +short norm.news

# 200, and the server header says cloudflare
curl -sI https://norm.news | head -5

# The page is really the landing page
curl -s https://norm.news | grep -o "<title>[^<]*"

# The card and icons are reachable. All three must be 200.
curl -sI https://norm.news/og.png | head -1
curl -sI https://norm.news/favicon.svg | head -1
curl -sI https://norm.news/apple-touch-icon.png | head -1

# www redirects to the apex, preserving the path
curl -sI https://www.norm.news/foo | grep -i "^location"

# http upgrades to https
curl -sI http://norm.news | head -1
```

Then check the two things a terminal cannot show you:

- **The shared-link card.** Paste `https://norm.news` into
  [opengraph.xyz](https://www.opengraph.xyz/). You should see the mug, the
  tracked `NORM'S NEWSLETTER` wordmark, the double rule and "Read less. Miss
  nothing." If the fonts look like a generic serif, the card was rendered
  wrongly; re-run `npm run og` and redeploy.
- **The real thing.** Send the link to yourself in whatever chat app you use and
  look at the preview. This is what everyone who ever receives the link sees.

Social platforms cache previews aggressively. If you change `og.png` later, the
old card can persist for days. Facebook's Sharing Debugger and LinkedIn's Post
Inspector both have a re-scrape button that clears it.

---

## Step 6. The waiting list

Steps 1 to 5 put a static page online. This step is what makes the Coming Soon
form do something: record the address and send one confirmation. Skip it and the
form still submits and still says "You are on the list", which is a lie the page
has already told in production.

Read `PROPOSED-SPEC.md` in this directory first. This is the only part of the
project that holds personal data, and it does so without a spec section.

### 6a. Resend, and proving you own the domain

1. Sign up at [resend.com](https://resend.com). The free tier is 3,000 emails a
   month, which is far more than a waiting list will ever use.
2. **Domains** → **Add domain** → `norm.news`.
3. Resend shows a handful of DNS records: a DKIM `TXT`, an SPF `TXT`, and
   usually an `MX` for bounce handling. Add each one in the Cloudflare
   dashboard under the `norm.news` zone → **DNS** → **Add record**.

   Copy the **Name** column exactly. Cloudflare appends the domain itself, so a
   name Resend shows as `resend._domainkey.norm.news` is entered as
   `resend._domainkey`. Getting this wrong is the usual cause of a domain that
   will not verify.

   Set every one of them to **DNS only**, not Proxied. Proxying is for HTTP and
   these are not HTTP records.
4. Back in Resend, **Verify**. It usually takes a few minutes.
5. **API Keys** → **Create API Key**, with **Sending access** and nothing more.
   Copy it once; Resend will not show it again.

Until the domain verifies, sends fail. That is survivable by design: the row is
written first, so nothing is lost, and `npm run waitlist` shows an empty
`emailed_at` for anyone who signed up in the gap.

### 6b. A real inbox behind norm@norm.news

The confirmation tells people to reply if they want off the list, so a reply has
to reach somebody.

1. Cloudflare dashboard → the `norm.news` zone → **Email** → **Email Routing**
2. **Get started**, and let Cloudflare add the records it asks for
3. Create a custom address: `norm@norm.news` forwarding to your real inbox
4. Confirm the forwarding address from the mail Cloudflare sends it

This is free and it is the whole removal mechanism. Without it the promise in
the email footer bounces.

> This is the case the note at the end of step 1 anticipated: MX records for
> this domain now live in Cloudflare, and Resend's bounce record and Email
> Routing's records have to coexist. Add both; they are on different names.

### 6c. The database

```bash
cd landing
npx wrangler d1 create norm-waitlist
```

It prints a `database_id`. Put it in `wrangler.toml`, replacing `REPLACE_ME`,
and commit that. It is an identifier rather than a credential: it names the
database and grants nothing, in the same way `GITHUB_OWNER` in
`ops/trigger-worker/wrangler.toml` names the repo.

Then create the table:

```bash
npx wrangler d1 execute norm-waitlist --remote --file=schema.sql
```

`--remote` matters. Without it you create the table in a local development copy
and the deployed endpoint writes to a database that has none.

### 6d. The API key

```bash
npx wrangler pages secret put RESEND_API_KEY --project-name norm-news
```

Paste the key when it prompts. It is stored by Cloudflare and never written to a
file (CLAUDE.md rule 5). Setting it once is enough; it survives every later
deploy.

### 6e. A limit on how fast the form can be used

A public form that sends email is a way to send mail to a stranger. The endpoint
already caps the damage at one message per address, ever, but the request rate
is worth capping too.

1. Cloudflare dashboard → the `norm.news` zone → **Security** → **Rate limiting
   rules** → **Create rule**
2. Name: `subscribe`
3. Match: field **URI Path**, operator **equals**, value `/api/subscribe`
4. Rate: **5** requests per **1 minute**, counting by **IP**
5. Action: **Block**, duration **10 minutes**
6. **Deploy**

### 6f. Deploy and check it

```bash
npm run build
npx wrangler pages deploy dist --project-name norm-news --branch main --commit-dirty=true
```

Then, from the terminal:

```bash
# A GET must be refused. If this returns 200 and HTML, the Function did not
# ship and the form is posting into the static site.
curl -sI https://norm.news/api/subscribe | head -1

# A real signup, to an address you can read
curl -s -X POST https://norm.news/api/subscribe \
  -H 'content-type: application/json' \
  -d '{"email":"you@example.com"}'

# The row, and whether the confirmation went out
npm run waitlist
```

Then check the things a terminal cannot: that the mail arrived, that it is not
in spam, that the mug renders at the top of it, and that replying to it lands in
your inbox.

If `emailed_at` is empty, the row was written and the send failed. Look at
**Workers & Pages** → **norm-news** → **Logs**: the endpoint logs the Resend
status and never the address. An unverified domain and a rejected key both show
up there plainly.

---

## Deploying a change later

```bash
cd landing
npm run build
npx wrangler pages deploy dist --project-name norm-news --branch main --commit-dirty=true
```

That is the whole loop, and it covers the Function as well as the page: Wrangler
compiles `functions/` on every deploy. The domain, certificate, redirect,
database and secret are all set up once and are not touched again.

Keep `--branch main`: drop it and the deploy silently becomes a preview, leaving
`norm.news` on the previous version with nothing obviously wrong.

Only run `npm run og` if you changed the card itself. It writes two PNGs into
`public/` that are committed to git, so it is not part of `npm run build` and
does not need to run on every deploy.

Useful afterwards:

```bash
npx wrangler pages deployment list --project-name norm-news
```

Every deployment keeps its own permanent preview URL, so rolling back is a
matter of promoting an older one from the dashboard.

---

## When it goes wrong

| What you see | What it usually means |
| --- | --- |
| `dig` still shows Porkbun nameservers | Step 1c has not propagated yet. Wait. |
| Domain stuck "Pending" in Cloudflare for over a day | Nameservers were typed wrongly at Porkbun, or DNSSEC is still on. Recheck both. |
| Domain does not resolve **at all**, anywhere | Almost certainly DNSSEC left enabled during the switch. Remove the DNSSEC records at Porkbun. |
| **522** on `norm.news` | Some other record is sitting on that name: either a leftover Porkbun parking record from step 1b, or one created by hand instead of through **Custom domains**. Delete it and redo step 3. |
| Bare domain shows a Porkbun "parked" page | The parking records in step 1b were not deleted. Remove them from the DNS tab. |
| **HTTPS certificate warning** | Normal for the first few minutes after step 3. If it lasts more than an hour, remove the custom domain and re-add it. |
| `norm-news.pages.dev` dead, but the hash and branch URLs work | The deploy went to Preview. `--branch main` was missing from 2c. Redeploy with it. |
| `norm.news` resolves and has a valid certificate but serves nothing | Same cause: no production deployment exists for the custom domain to serve. |
| A deploy appears to do nothing | It landed as a preview. Check the Environment column in `pages deployment list`. |
| Page loads but is unstyled, or 404s on assets | `dist/` was stale or incomplete. Re-run `npm run build`, confirm the four files exist, redeploy. |
| Shared link shows no image | `og.png` returned non-200, or the platform cached an older scrape. Check with `curl` first, then force a re-scrape. |
| `wrangler` cannot find the project | Wrong Cloudflare account. Run `npx wrangler whoami`. |
| `GET /api/subscribe` returns the landing page | The Function did not ship. Deploy from `landing/`, not from the repo root: Wrangler looks for `functions/` in the directory you run it from. |
| Signups appear but `emailed_at` is always empty | Resend is refusing the send. The Pages logs name the status: usually an unverified domain (step 6a) or a missing key (step 6d). |
| `npm run waitlist` prints nothing on a list that has people | It ran against the local copy. The script passes `--remote` unless you give it `--local`. |
| The confirmation lands in spam | The SPF or DKIM record in step 6a is missing or wrong. Check the domain still shows Verified in Resend. |

## What this does not cover

- **A spec section for this page.** Under CLAUDE.md rule 1 the landing page is
  still an unapproved working draft, and deploying it does not change that. See
  `README.md` in this directory, and `PROPOSED-SPEC.md` for the waiting list,
  which is the part of it that holds personal data.
- **The Astro site.** Untouched, still on GitHub Pages. If it ever moves onto
  this domain it needs a subdomain such as `news.norm.news`, because the bare
  `norm.news` is now the landing page.
- **Automatic deploys on push.** This is a manual `wrangler pages deploy`. You
  could connect the Pages project to the GitHub repo instead, but that coupling
  has to be rewired when SPEC 13 moves the repo to a new organization, in the
  same way step 4b of that plan rewires the trigger Worker.
