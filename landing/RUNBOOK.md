# Looking after norm.news

`DEPLOY.md` is how the landing page got onto `norm.news`. You follow it once.
**This file is the other half: how to keep it working, ship changes to it, and
notice when something is quietly wrong.** You come back to this one.

It mirrors the root `RUNBOOK.md`, which does the same job for the newsletter
pipeline. The two systems are separate and neither can break the other.

---

## 1. What you are actually running

It looks like one website. It is six things, and they fail in different ways.

| Part | What it does | If it breaks |
| --- | --- | --- |
| **The domain** (`norm.news`) | Porkbun owns the name, Cloudflare answers for it | Everything is gone |
| **The page** | Static files on Cloudflare Pages | Visitors see nothing or something stale |
| **The form** (`/api/subscribe`) | A Pages Function, runs only when someone signs up | Signups fail, or worse, *appear* to work |
| **The database** (`norm-waitlist`) | A Cloudflare D1 table holding the email addresses | You lose signups |
| **Resend** | Sends the one confirmation email | People sign up and hear nothing |
| **Email Routing** | Forwards `norm@norm.news` to a real inbox | You never see the people asking to be removed |

The first two are boring and reliable. **The last four are where the attention
goes**, because between them they hold other people's personal data and send
mail on your behalf.

---

## 2. Read this part even if you read nothing else

### The form tells everyone it worked, even when it did not

This is deliberate, it is the right design, and it is also the single easiest
way for this site to be broken for weeks without anyone noticing.

Here is the chain. `functions/api/subscribe.js` writes the address to the
database **first**, then tries to send the confirmation. If the send fails, it
still answers the browser with success and leaves the `emailed_at` column empty.
The page, in `src/App.jsx`, shows its thank-you state for any successful
response.

That is correct, and the reasoning is worth understanding rather than just
accepting: **the signup is the thing that cannot be lost, and the confirmation
can always be sent again later.** If a Resend outage made the form fail, you
would lose real subscribers to a problem that only delayed an email. So the
failure is absorbed on purpose.

The cost of that choice is that **nothing anywhere will tell you.** The visitor
is happy. The page is fine. No alert fires. The only trace is an empty
`emailed_at`, and the only thing that looks at it is you:

```bash
cd landing
npm run waitlist
```

Read the **last line**, which it prints to your terminal rather than into the
CSV:

```
14 on the list
14 on the list, 3 with no confirmation sent     <-- this needs you
```

Anything other than zero unsent means Resend has been rejecting mail. Section 6
is how to work out why.

**If you only ever do one maintenance task on this site, make it running that
command once a week.**

### Never mass-email this list yet

`PROPOSED-SPEC.md` carries this as a hard rule and it belongs here too, because
the moment it gets broken is a launch day when somebody is excited.

The confirmation is **transactional**: a person pressed a button and the mail
confirms the button worked. "Reply with the word off" is a good enough removal
path for that.

A launch announcement sent to everyone at once is **marketing**, legally a
different thing under both CAN-SPAM and GDPR, and reply-based removal is not
enough for it. It needs a real one-click unsubscribe link, a
`List-Unsubscribe-Post` header, and a suppression list that outlives the deleted
row.

**Nothing is broadcast to this list until that exists.** Building it is a
project, not an afternoon. Resend Audiences provides all three and is the thing
to reach for when the day comes.

---

## 3. Shipping a change

### The loop

```bash
cd landing
npm run build
npx wrangler pages deploy dist --project-name norm-news --branch main --commit-dirty=true
```

That covers the page and the Function together; Wrangler compiles `functions/`
on every deploy. The domain, certificate, redirect, database and API key are set
up once and are never touched again.

Three things to keep in mind, each of which has already caught someone:

- **Run it from `landing/`, not the repo root.** Wrangler looks for `functions/`
  in the directory you are standing in. From the root it finds none, deploys the
  page without the form, and every signup posts into a static file.
- **Keep `--branch main`.** Without it Wrangler reads your git branch, and
  anything other than `main` is filed as a *preview*: a perfectly working URL
  that `norm.news` does not serve. The deploy appears to succeed and the live
  site simply does not change.
- **`dist/` is what ships.** Not your git branch, not your last commit. If you
  did not re-run `npm run build`, you just redeployed the previous version.

### Before you deploy

```bash
npm run build
ls dist/index.html dist/og.png dist/favicon.svg dist/apple-touch-icon.png
```

All four must exist. Then look at the page locally with `npm run dev`, and if
you touched the form, `npm run dev:api` instead, which is the only mode that
runs the Function.

### After you deploy

```bash
# Did it actually go to production?
npx wrangler pages deployment list --project-name norm-news | head -5

# Is the live page the new one?
curl -s https://norm.news | grep -o "<title>[^<]*"
```

Then open `https://norm.news` in a browser and hard-reload (Cmd-Shift-R).

**The shared-link card no longer tracks the hero.** It used to be generated from
the hero's tagline, so changing that copy meant regenerating it. It is now a
supplied image, `public/og.png`, and nothing regenerates it. Changing the hero
does not change the card, and it is not supposed to.

**If you replace `public/og.png`**, bump the `?v=` number on the two `og:image`
and `twitter:image` tags in `index.html` in the same commit. Facebook, LinkedIn
and Twitter cache the card by URL, so without the bump they keep showing the old
picture for days. Keep it 1200x630; anything else gets cropped by someone.

### Undoing a bad deploy

Every deployment keeps its own permanent URL forever, so nothing is ever really
lost.

```bash
npx wrangler pages deployment list --project-name norm-news
```

Find the last good one, open its URL to confirm it is the version you want, then
in the dashboard under **Workers & Pages → norm-news → Deployments**, use
**Rollback** on that deployment. This is faster and safer than trying to rebuild
the old version from git, especially at the moment you most want it.

---

## 4. Routine checks

Nothing here watches itself. There is no alerting, and for a page of this size
that is a reasonable choice, but it does mean the checks are yours.

### Weekly, about two minutes

```bash
cd landing
npm run waitlist
```

You are looking for two things:

1. **The unsent count in the last line is zero.** Anything else means mail is
   failing. Go to section 6.
2. **The numbers move the way you expect.** A sudden jump of hundreds is not
   good news, it is a bot getting through. See section 7.

Then load `https://norm.news` in a browser and check it looks right.

### Monthly, about ten minutes

Run the full check block:

```bash
# The page is up and served by Cloudflare
curl -sI https://norm.news | head -3

# Assets that the page and the shared-link card need
for f in og.png favicon.svg apple-touch-icon.png; do
  echo -n "$f: "; curl -so /dev/null -w "%{http_code}\n" https://norm.news/$f
done

# www still redirects to the bare domain, keeping the path
curl -sI https://www.norm.news/foo | grep -i "^location"

# The form endpoint exists and refuses GET. 405 is correct.
# A 200 here means the Function did not ship.
curl -so /dev/null -w "%{http_code}\n" https://norm.news/api/subscribe
```

Expected: `200`, three `200`s, a `location` of `https://norm.news/foo`, and
`405`.

Then do the two things a terminal cannot check:

- **Sign yourself up** with a real address you can read, using a `+` alias like
  `you+aug@gmail.com` so it is a new address every time. Confirm the mail
  arrives, lands in the inbox rather than spam, shows the mug at the top, and
  that replying to it reaches you. Then delete the test row (section 5).
- **Paste `https://norm.news` into [opengraph.xyz](https://www.opengraph.xyz/)**
  and confirm the card still renders.

Also glance at **Resend → Domains** and confirm `norm.news` still says
**Verified**. This is the one that rots quietly: if the DNS records ever get
tidied away, verification lapses and every send fails from that moment on.

### Once a year, and put it in a calendar

- **Renew the domain at Porkbun.** Turn on auto-renew and make sure the card on
  file is current. This is the only failure on this whole page that cannot be
  fixed in an afternoon: an expired domain can be bought by someone else.
- **Consider rotating the Resend API key.** `wrangler pages secret put
  RESEND_API_KEY --project-name norm-news`, then delete the old key in Resend.

---

## 5. Looking after the list

### Reading it

```bash
npm run waitlist              # to the screen
npm run waitlist > list.csv   # to a file
```

There is no admin page and no web read path, on purpose. Seeing the list
requires an authenticated Cloudflare account, which is the intended bar for a
table of other people's email addresses. Do not build a page that shows it: that
is a second door to the same data, and there is no requirement that needs one.

### Removing someone

The confirmation email promises "reply with the word off and you are removed."
**That promise is kept by hand, by you.** Nothing is automated. Some mail
clients also show a native Unsubscribe button, which sends the same reply, so
removal requests arrive as ordinary email to `norm@norm.news`.

```bash
npx wrangler d1 execute norm-waitlist --remote \
  --command "DELETE FROM waitlist WHERE email = 'them@example.com'"
```

One statement, one table, nothing else to chase. Do it promptly. A person who
asked to be removed and is still on the list next month is the exact thing the
promise was meant to prevent.

**So the inbox behind `norm@norm.news` is not optional.** If nobody reads it,
the removal path silently does not exist.

### Backups

Two independent safety nets, and it is worth knowing which is which:

- **Cloudflare Time Travel**, automatic, restores the database to any point in
  the last **7 days** on the free plan. Good for "I just deleted the wrong row."
  Useless for anything you notice late.
- **Your own CSV**, manual. `npm run waitlist > waitlist-YYYY-MM-DD.csv`, kept
  somewhere off this laptop. Do this monthly.

Seven days is short. The CSV is what actually protects you.

**Do not commit that CSV to the repo.** It is other people's email addresses,
git history is permanent, and a deletion request cannot reach it.

### The open question nobody has answered

The table has **no retention period**. Every other piece of personal data in
this project has one, set by SPEC 14.12. This one does not, because
`PROPOSED-SPEC.md` proposed it and has not been approved.

The proposal is: delete a row once that person has an account, and delete the
table outright once the app has launched and the last update has gone out. The
list exists to send two messages, and a list with no purpose is a liability
rather than an asset. Until that is decided, this is a known gap rather than a
settled position.

---

## 6. When mail stops going out

The symptom is `npm run waitlist` reporting a non-zero unsent count. Visitors
saw nothing wrong.

**Look at the logs first.** Cloudflare dashboard → **Workers & Pages** →
**norm-news** → **Logs**. The endpoint records the Resend status code and its
message, and deliberately never records the recipient. The cause is usually
named outright.

| What the log says | What it means | Fix |
| --- | --- | --- |
| `no RESEND_API_KEY` | The secret is missing from this project | `npx wrangler pages secret put RESEND_API_KEY --project-name norm-news` |
| `resend 401` / `403` | The key is wrong, revoked, or from another account | Issue a fresh key in Resend, set it again |
| `resend 403` mentioning the domain | Domain verification lapsed | Resend → Domains → re-verify, check the DNS records still exist in Cloudflare |
| `resend 429` | Over the rate or daily limit | See section 7 |
| `resend unreachable` | Resend had an outage | Nothing to fix. Send the backlog once it clears. |
| `no DB binding` | The database is not attached to this deployment | Check `wrangler.toml` has a real `database_id`, not `REPLACE_ME`, and redeploy |

**Once it is fixed, the backlog does not send itself.** The rows are there with
`emailed_at` still empty. Get the addresses:

```bash
npm run waitlist | grep ',$'
```

Those are the people who signed up and heard nothing. Write to them, then mark
them so they do not show up again next week:

```bash
npx wrangler d1 execute norm-waitlist --remote \
  --command "UPDATE waitlist SET emailed_at = '2026-08-06T12:00:00Z' WHERE emailed_at IS NULL"
```

---

## 7. Limits, and what happens when you hit one

Everything here is on a free plan. The headroom is large for a waiting list, but
the failure modes differ and it is worth knowing which cliff you would fall off.

| | Free allowance | What happens at the limit |
| --- | --- | --- |
| **Page views** | Not metered | Static files on Pages do not count against the Workers quota |
| **Form submissions** | 100,000 / day, resets midnight UTC | Cloudflare error 1027, the form stops working |
| **Resend** | 100 / day, 3,000 / month, 1 domain | Sends are refused, `emailed_at` stays empty, signups still recorded |
| **Database size** | 500 MB | Not reachable. An email address is ~40 bytes. |
| **Files in a deploy** | 20,000 files, 25 MiB each | The hero video is the largest file at under 1 MB |

The realistic risk is **Resend's 100 a day**, and only from abuse rather than
success. Two protections already exist and are worth understanding because they
are each one edit from being removed:

1. **One address, one email, ever.** `email` is the table's primary key and the
   insert is `ON CONFLICT DO NOTHING`. A repeat submission writes nothing and
   sends nothing. This is what stops the public form being a way to repeatedly
   mail a stranger whose address an attacker typed in.
2. **A hidden honeypot field.** The form renders an empty `company` field off
   screen. A bot that fills every field trips it, and the endpoint answers with
   success and writes nothing, because telling a bot it failed only teaches it
   to try again differently.

Plus the rate limiting rule from DEPLOY.md step 6e, capping one IP at 5 requests
a minute.

**If you see a sudden burst of signups, do not celebrate.** Export the CSV and
look at the addresses. Runs of random characters at the same domain, or a
hundred rows in a minute, mean a bot found a way through. Tighten the rate limit
first, since it is the one lever that needs no deploy.

---

## 8. Something is wrong and it is not in here

`DEPLOY.md`'s **When it goes wrong** table covers the setup-time failures: DNS,
certificates, preview-versus-production, missing Functions. Check there first,
because most of those can also happen later.

Beyond that:

| Symptom | Where to look |
| --- | --- |
| Whole site down, `dig norm.news` returns nothing | Domain expired, or DNSSEC. Check Porkbun first. |
| Site up but very old content | A deploy went to preview. `pages deployment list`. |
| Form returns 500 | Database binding. Pages logs will say `no DB binding`. |
| Form returns 405 to the real form | Something is sending GET instead of POST. Only a code change causes this. |
| Everything looks fine, no signups for weeks | Test it yourself. A form nobody can use looks identical to one nobody wants. |

**Stop and ask rather than improvise if:** personal data may have been exposed,
you are about to email the whole list, you are considering a schema change to
`waitlist`, or you are about to add a column that records anything about a
person beyond their address. The first is an incident, and the other three each
need `PROPOSED-SPEC.md` resolved first.

---

## 9. What this page still owes

Worth knowing so it is not mistaken for finished work:

- **No spec covers it.** Under CLAUDE.md rule 1 the landing page is an
  unapproved working draft. `README.md` here lists the claims it makes that
  SPEC.md does not carry.
- **No retention period** on the waiting list. Section 5.
- **No real unsubscribe**, so no broadcast. Section 2.
- **No monitoring.** Every check in this file is manual. If this page ever
  matters more than it does today, an uptime check on `https://norm.news` and a
  scheduled job asserting the unsent count is zero are the two things worth
  adding first.
