# Proposed spec addition: the waiting list

**Status: a proposal. It governs nothing.** Under CLAUDE.md rule 1 this should
have been written and approved before the code it describes. It was not, and
that is worth stating plainly rather than presenting the code as covered.

This exists because the landing page now holds **personal data**, which is the
first time anything in this project has. Everything else the page does is a
design question. This one touches decision #36, section 14.12, and the promise
the product makes about deletion, so it needs a decision rather than a note.

The rest of `landing/` is unspecified too, for reasons `README.md` records.
This section is separated from that because the others are claims on a page and
this is a table of other people's email addresses.

---

## What exists today

`functions/api/subscribe.js` on Cloudflare Pages, writing to a Cloudflare D1
database named `norm-waitlist` on the same account that holds R2 and the
publish trigger Worker. One table:

| Column | Type | Meaning |
| --- | --- | --- |
| `email` | TEXT, primary key | Lowercased and trimmed |
| `created_at` | TEXT | ISO 8601, UTC |
| `emailed_at` | TEXT, nullable | Null means the confirmation never sent |
| `source` | TEXT | `landing` |

There is no IP address, user agent, country or referrer, and no column that
could carry one. Nothing about a person is recorded except that they asked to
be told when the app opens.

On a new address the endpoint sends one confirmation through Resend from
`norm@norm.news`. On an address already present it sends nothing, so **one
address receives at most one message from this endpoint for as long as the row
exists.** Removal is by reply, forwarded to a real inbox by Cloudflare Email
Routing, and is a single `DELETE`.

## The four questions this owes an answer to

### 1. Does this break decision #36?

Decision #36 says personal data lives in Postgres and never in the lake. This
data is in neither. The deciding argument in #36 was not the choice of
database, it was that **deletion has to be one operation**, which Iceberg's
append-only snapshots cannot give and a relational table can.

That property holds here: one table, four columns, one statement to erase a
person. The lake is untouched, so #36's actual guarantee is intact.

What is not intact is the *enumeration*. 14.12 says deletion "removes every row
keyed to that `user_id` in Postgres", and correctness depends on the list of
places being complete. There is now a place outside that list. **Either this
table joins the enumeration or the spec has to say why it is exempt.**

The case for exempt: a waiting list subscriber is not an account holder. There
is no `user_id` to key on, no login, and nothing to delete in the app because
they have no app. The two datasets never join.

Recommendation: **keep it separate and name it explicitly** in 14.12 as a
second place personal data lives, with its own deletion path. Folding a
pre-signup list into the account tables at M7 would mean matching people by
email address across two systems, which creates the join it is trying to
avoid.

### 2. How long is it kept?

14.12 sets a retention period for every other piece of personal data in the
system. This table has none, which makes it the only personal data here with no
clock on it.

Proposed: **delete a row once the person it belongs to has an account, and
delete the table outright once the app has launched and the last update has
been sent.** The list exists to send two messages. When both are sent it has no
purpose, and a list with no purpose is a liability rather than an asset.

If a periodic clock is wanted instead, 24 months matches the longest thing this
could plausibly be waiting for.

### 3. Is the confirmation transactional or marketing?

Transactional. Somebody typed an address into a form and pressed a button, and
the mail confirms that the button worked. That is why a reply-based removal is
sufficient for it.

**The first broadcast is a different thing, and this is the trap.** A message
sent to everyone at once, months later, about a product launch, is marketing
under both CAN-SPAM and GDPR, and reply-based removal is not enough for it. Any
such send needs a real unsubscribe first: a one-click link, a
`List-Unsubscribe-Post` header, and a suppression list that outlives the row.
Resend Audiences provides all three, which is the reason to reach for it at
that point rather than now.

**Nothing should be broadcast to this list until that exists.**

### 4. What does the page promise, and is it true?

The form says "One address. Zero noise. We will only email you with major
milestones and system release dates." That is a commitment, and it is currently
true because the only send that exists is the confirmation.

It stops being true the first time this list is used for anything else. It is
recorded here so it is a decision rather than a drift.

## What is deliberately absent

- **No double opt-in.** A confirmation that asks the person to confirm again
  is the correct answer for a list that will be marketed to. For a list whose
  entire content is "we will tell you when it opens", it doubles the failure
  modes to prevent a harm the one-mail-per-address rule already caps at one
  message.
- **No analytics columns.** See the table above and the comment in
  `schema.sql`.
- **No admin page.** The list is read with `npm run waitlist`, which needs an
  authenticated Cloudflare account. A web read path is a second door to the
  same data and there is no requirement that needs one.
- **No storage of the address in logs.** The endpoint logs failure causes and
  never recipients, because Cloudflare's logs would be a third place holding
  personal data and would not be reachable by a deletion.
