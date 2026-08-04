# APP-ARCHITECTURE.md

**Status: proposal, not approved spec.** SPEC.md and DESIGN.md remain
authoritative. Nothing in this file governs the build until it is folded into
SPEC.md and approved. This document exists to explain the plan in plain
English so anyone joining the project can understand it quickly.

Written 2026-08-03. Reconciled with SPEC.md section 14 on 2026-08-04.

---

## Read this first: what has changed since this was written

Everything below was written as a proposal. Most of it is now specified in
**SPEC.md section 14**, and in several places the specification went a
different way after the app prototype was read against it. **SPEC.md wins
everywhere.** The reconciliation:

| This document said | The spec decided | Where |
| --- | --- | --- |
| Store the embeddings | They are a cache keyed by `(item_id, model_version)`. A miss just recomputes | #35 |
| Allocator has a per-topic minimum and maximum, budget 12 to 18 | The reader sets the length and a weight per topic; stories split in proportion to the weights. No minimum or maximum | #45, SPEC 14.4 |
| One lookback window | Two: 36 hours normally, 7 days for catch-up. Score ties break by recency | #48 |
| 30 to 50 curated topics | Ten: exactly the topics already in the enum | #49, SPEC 14.3 |
| Two-host audio dialogue | A single voice reading self-contained per-story segments | #44 |
| Nothing on money | Free tier is a cap of three ranked topics; Pro is $9.99 a month or $100 a year, through in-app purchase | #46, #47, SPEC 14.10 |
| Nothing on sign-in | Sign in with Apple plus email magic links. No social logins, no passwords | #50, SPEC 14.2 |
| "Instrument feedback telemetry" as a warning | Four events, specified and shipping in v1 | #51, SPEC 14.11 |
| Nothing on retention | 12 months for stories, newsletters and seen-story history; 13 for telemetry | #55, SPEC 14.12 |
| Nothing on top-up limits | Floor of 6 on `general_score`, and at most half the budget | #56 |

Two things the spec added that this document never considered: push
notification copy comes from deterministic templates and never from a model
(#52), because a generated notification would be a second AI call on the
per-user path; and the app has no edition number at all (#53), because the
site's sequential numbering is a fact about the site rather than about any
reader.

Section 15 below is kept as a record of what was open on 2026-08-03. Every
item in it is now closed.

---

## Table of contents

1. [What is changing](#1-what-is-changing)
2. [The core idea: write once, reuse for everyone](#2-the-core-idea-write-once-reuse-for-everyone)
3. [Where the data lives](#3-where-the-data-lives)
4. [How the schedule works](#4-how-the-schedule-works)
5. [Two scores per story](#5-two-scores-per-story)
6. [Stories belong to more than one topic](#6-stories-belong-to-more-than-one-topic)
7. [The allocator: choosing what goes in each newsletter](#7-the-allocator-choosing-what-goes-in-each-newsletter)
8. [Topics: fixed menu for v1](#8-topics-fixed-menu-for-v1)
9. [Never show an empty app](#9-never-show-an-empty-app)
10. [Adding more sources](#10-adding-more-sources)
11. [Audio](#11-audio)
12. [Infrastructure](#12-infrastructure)
13. [Deployment and CI/CD](#13-deployment-and-cicd)
14. [Things that will bite us later](#14-things-that-will-bite-us-later)
15. [Decisions still open](#15-decisions-still-open)
16. [Glossary](#16-glossary)

---

## 1. What is changing

**Before:** one newsletter, published once a day at 6am ET, the same for
everybody. An AI editor picked 15 to 20 stories, AI writers wrote each one,
and the result was published as a static website.

**After:** every user builds their own newsletter. They pick the topics they
care about and the time of day they want to read. The app then shows them a
newsletter made only of stories in their topics, delivered at their chosen
time.

That sounds like a small change. It is not. Doing it the obvious way would
make the product about fifty times more expensive to run. Most of this
document is about avoiding that.

---

## 2. The core idea: write once, reuse for everyone

This is the most important idea in the whole design. Everything else follows
from it.

There are two ways to build a personalized newsletter.

### The expensive way (do not do this)

For each user, gather their stories and ask the AI to write their newsletter.
Every user triggers their own AI calls.

### The cheap way (what we are doing)

The AI writes each **story** exactly one time. A story about a Federal Reserve
rate decision reads the same whether one person or ten thousand people open
it. So we write it once, save it, and reuse it.

When a user opens the app, we do not generate anything. We **look up** which
already-written stories match their topics. That is a database query. No AI
involved.

### Why this matters so much

Using Claude Haiku 4.5 pricing ($1 per million input tokens, $5 per million
output tokens), a single story-writing call costs roughly $0.0055.

| Approach | Calls per day | Cost per month at 1,000 users | Cost at 10,000 users |
| --- | --- | --- | --- |
| Write per user (1,000 users x 15 stories) | 15,000 | ~$2,475 | ~$24,750 |
| Write per story, reuse (~300 stories/day) | 300 | ~$50 | ~$50 |

Read that second row again. **The cost does not change when users are added.**
Our bill is tied to how much news happened today, not to how many people are
reading. That is the difference between a product that can grow and one that
cannot.

Prompt caching and the Batch API can cut both numbers by roughly half, but
they do not change the shape. One grows forever. One does not.

### The mental model

Think of it as a newsroom. The newsroom writes the day's stories once. Every
reader gets a custom front page assembled from those same stories.

**The writing is shared. The assembly is personal.**

### The one exception

The personalized intro ("here is what is happening in your world today")
genuinely has to be per user, because it is about *their* particular mix of
stories. That is fine, because it is cheap. It costs roughly $0.0028 per user
per day, so about $83 a month at 1,000 users.

We can cut that further. Many users end up with the same set of stories. If we
generate the intro once per unique set of story IDs and reuse it, the cost
drops to roughly $17 a month.

---

## 3. Where the data lives

We need three different storage systems, because we have three kinds of data
with three very different needs. Using one system for all of them will hurt.

### 3.1 The data lake (Iceberg on Cloudflare R2)

**What it holds:** the news pipeline. Raw collected items, deduplicated and
clustered stories, scores, and historical archives.

**Why:** this data is written constantly and read in bulk. It is cheap to
store and good for "scan a million rows and summarize." No user's phone ever
talks to it directly.

**Change from today:** almost none. Keep it as it is.

### 3.2 A regular database (Postgres). This is new.

**What it holds:** everything about people. Accounts, chosen topics, chosen
read time and timezone, which stories they have already seen, push
notification tokens, billing.

**Why a separate system?** A data lake answers "summarize a million rows."
A phone app asks "give me *this one user's* settings in 50 milliseconds."
Those are opposite problems and no single system is good at both.

There is a second reason that matters more than performance. When someone
deletes their account, we are legally required to actually delete their data.
Apple also requires an in-app delete option (App Store Guideline 5.1.1(v)).
In Postgres that is one `DELETE` statement. In an append-only data lake with
time travel it is a genuinely hard engineering problem. Keeping personal data
out of the lake entirely avoids all of it.

### 3.3 The finished newsletters

**What it holds:** each user's assembled newsletter, ready to serve.

**Where:** Postgres, or a simple key-value store keyed by `user_id + date`.
The app calls an API, the API reads a pre-built newsletter, done. Fast.

### Two schema rules to follow from day one

1. **Put `user_id` on things immediately**, even while testing with a single
   account. Adding it later means migrating everything.
2. ~~Start saving the embeddings.~~ **Superseded by decision #35.** The
   instinct was right but storing them would have given up a property worth
   keeping: because nothing is stored, changing the embedding model costs a
   threshold re-calibration and no data migration. They are a **cache** keyed
   by `(item_id, model_version)` instead. A miss recomputes exactly as before,
   and a model change invalidates by version rather than needing a migration.

---

## 4. How the schedule works

Users pick their own read time. This changes the pipeline shape, and for the
better.

### Why one daily batch does not work

Users read at 6am in Tokyo, 7am in London, and 8am in Los Angeles. Those are
sixteen hours apart. If we write all the stories in one morning batch,
somebody is always reading stale news.

### Continuous writing instead

The collector already runs every few hours. Let the writing follow the same
rhythm. Whenever a new story cluster clears the quality bar, write it right
then and save it. Stories accumulate through the day.

This costs exactly the same as batching (it is still one write per story), but
everybody gets fresher news.

### The two loops

```
CONTINUOUSLY (every few hours):
  collect sources
    -> deduplicate
    -> cluster into stories
    -> score
    -> write any new story that clears the bar
    -> save to the stories table

EVERY 15 MINUTES:
  find users whose read time is coming up
  for each one:
    query their topics
    pick the best stories they have not seen
    generate their intro
    save the finished newsletter
  send the push notification at their chosen time
```

The per-user loop is fast and cheap because the hard work already happened.

### Two things to get right about time

**Store the timezone, not a fixed hour.**
Save `6:30am, America/New_York`. Do **not** save `11:30 UTC`. If we store UTC,
everybody's read time silently shifts by an hour when daylight saving changes.
We already know this pain from the publish schedule (SPEC section 6.8).

**"Today's newsletter" is defined per user, not globally.**
For someone in Tokyo reading at 6am, it is still the previous afternoon in New
York. The clean answer is: a user's newsletter is dated in *their* local
timezone and contains the best stories available at the moment it was
assembled.

Two users in different timezones will see different content on the same
calendar day. **That is correct, not a bug.** Do not try to make everyone
share one global "edition date." It will not work and we will fight it
forever.

---

## 5. Two scores per story

**This is the most important technical change in this document.** Get it wrong
and the app has a category of users who see nothing.

### The problem

Our current scoring is a *general newsworthiness* score. It was designed for
one edition read by a general audience. The Sports decision (SPEC decision
log #32) says it out loud: routine sport is capped at 3, and a sports story
needs significance beyond the result to reach 6.

That was exactly right when sport competed against real news for 20 shared
slots.

Now think about a user who subscribes to Sports and nothing else.

Their entire newsletter is sports. Every story in it scores 3. If we apply any
quality floor at all (say, only show stories scoring 6 or above), **that user
gets an empty newsletter forever.** If we drop the floor to fix it, we break
quality for everyone else.

The rubric that protects a general edition actively destroys a personalized
one.

### The fix

Produce **two scores from the same AI call**, so it costs nothing extra.

| Field | Question it answers | Used for |
| --- | --- | --- |
| `topic_score` | How important is this *within its topic*? | Ranking stories inside a user's chosen topics. This is what personalization uses. |
| `general_score` | How important is this to a general reader? | Choosing the lead story, and filling gaps for users whose topics are quiet. |

A major transfer is a 9 on `topic_score` for Sports even though it is a 3 on
`general_score`. Both are true. They answer different questions.

### Why decide this now

Changing it later means re-scoring the entire history. It is a small change
today and an expensive one in six months.

---

## 6. Stories belong to more than one topic

Right now a story cluster gets exactly one topic.

Consider a story about US chip export restrictions. It is genuinely Tech,
Business, US Politics, **and** Regulation.

With one topic, we pick Tech. Every Business subscriber who would have wanted
it never sees it. Multiply that across a few hundred stories a day and
personalization starts feeling thin for no good reason.

### The fix

Give each story:

- a **primary topic** (where it "lives," used for section placement), and
- **secondary topics** (where it also reaches).

Same AI call, same cost, much better coverage.

---

## 7. The allocator: choosing what goes in each newsletter

Here is the part that "the newsletter is just a query of the user's topics"
quietly skips over.

### The problem

If each topic keeps its top 10 stories and a user picks 8 topics, they get 80
stories. That is not a newsletter, that is a firehose. If a user picks 1
topic, they get 10. Neither is right.

What we actually need is the job the AI editor does today, but written as
**deterministic code**, because we cannot afford an AI call per user.

This is good news. As code it is cheaper, faster, testable, and predictable.
All four are improvements over a prompt.

### The rules the allocator needs

> **Superseded by decision #45. SPEC 14.4 is authoritative.** The rules below
> assumed the system chooses the budget and guards each topic with a minimum
> and a maximum. The app prototype showed a better answer: the **reader**
> chooses the length and gives each topic a weight, and stories split in
> proportion to those weights. A minimum and a user-set weight do the same job,
> and the minimum wins silently, so the reader's setting appears to work and
> does not. The rules that survive are 4, 5, 6 and 7 below; rules 1 to 3 are
> replaced by the weights.

1. ~~A total budget per newsletter, say 12 to 18 stories.~~ The reader picks a
   length: 5, 8, 11, 16 or 20, defaulting to 11.
2. ~~A minimum and maximum per topic.~~ Each topic carries a weight from 1 to
   10, and gets that share of the length. A topic can legitimately get zero,
   and the app says so in the label the reader sees.
3. ~~Fewer topics means more stories per topic.~~ This is now arithmetic
   rather than a rule: one topic means a share of 1.0 and the whole length.
4. **Remove duplicates.** With secondary topics (section 6), the same story
   can now appear under several of a user's topics. Show it once, and record
   which topic claimed it. The topic earliest in the reader's own order wins.
5. **Skip anything they have already seen.**
6. **Top up from general news** if their topics are quiet, using
   `general_score`. Bounded since decision #56: nothing below 6, and never
   more than half the newsletter.
7. **Pick the lead story** as the highest `general_score` among the stories
   selected.

### A worked example

Updated for the weighted allocator. A reader on Pro picks Tech at weight 8,
AI at 5, Sports at 2, and a length of 11 ("As filed").

```
Step 1  Entitlement. Pro, so all three topics run. On the free tier
        only the first three ranked topics would, which here is all
        of them anyway.

Step 2  Query Tech, AI, Sports (primary OR secondary), inside the
        36-hour daily window, excluding already-seen.
        Result: 47 candidates.

Step 3  Dedup. A story tagged both Tech and AI appears once, claimed
        by whichever the reader ranked higher.
        Result: 41 stories.

Step 4  Targets. Weights total 15, so shares are 8/15, 5/15, 2/15
        of 11 stories = 5.87, 3.67, 1.47.
        Floors are 5, 3, 1 = 9. Two seats left, given to the two
        largest remainders (Tech .87, AI .67).
          Tech   -> 6
          AI     -> 4
          Sports -> 1        total 11

Step 5  Fill by topic_score, breaking ties by which is newer.
        Tech and AI fill. Sports has nothing today, as usual.

Step 6  Reclaim. Sports releases its 1 seat. It goes to Tech, which
        has the larger weight and unselected candidates left.
          Tech 7, AI 4, Sports 0     total 11

Step 7  Top up. Not needed, the budget is full. If it were short,
        general news scoring 6 or better would fill it, up to half
        the newsletter and no further.

Step 8  Lead story = highest general_score of the 11.

Step 9  Generate the intro from the 11 one-line summaries.
        (Cache it by the hash of the story ID set.)
```

Every step above is plain code. No AI except step 9.

Note what step 6 does for the Sports subscriber. Sports produces nothing on
most days, so its seat goes to a topic that does. The reader still sees Sports
whenever something clears, which is exactly what the weight of 2 asked for.

---

## 8. Topics: fixed menu for v1

There are two ways to let users pick topics.

**A fixed menu.** Curated topics, and the user checks boxes. Simple,
predictable, and our existing scoring already works this way. This document
guessed 30 to 50; **decision #49 settled on ten, which is exactly the topics
already in the enum.** Each topic carries anchored 3, 6 and 9 example stories
in the scoring prompt, so thirteen extra topics means thirteen more anchor sets
to write and calibrate. The app prototype's twenty are recorded in SPEC 14.3 as
a deferred expansion.

**Free text.** The user types anything ("Formula 1", "my city council"),
matched by meaning using embeddings. Flexible, but harder, and it fails badly
on vague input.

### We are starting with the fixed menu. Here is the specific reason.

Our scoring step **cannot say "this story does not fit any topic."** It has to
pick one from a closed list. So an unmatched story does not get dropped, it
gets **filed under the wrong topic**, where it pollutes a real category.

That is exactly what the Sports decision was about (SPEC decision log #32).
With free-text topics, that failure mode gets much worse and much harder to
detect.

Custom free-text topics come later, as a separate feature layered on top.

---

## 9. Never show an empty app

Our current rule is that a day is never left unpublished (SPEC decision #26).
That rule is much harder to keep per user, because someone with two niche
topics will hit quiet days often.

**Make "top up with general news" the default behavior, not an error case.**

Two moments matter most:

### When someone adds a new topic

The obvious behavior is "you will start seeing it tomorrow." Do not do that.
The moment someone adds a topic is the moment they are deciding whether the
app is worth keeping. An empty result is the worst possible timing.

Because stories are written globally and stored, we can fill in the last few
days of that topic **instantly and for free**. The stories already exist. It
is just a query.

This is a direct benefit of the write-once architecture, and it is nearly
impossible to add later if we build it the other way.

### On the very first run

Someone signs up at 3pm and their read time is 7am tomorrow. Do not make them
wait sixteen hours to find out if the app is good. Build their first
newsletter immediately from the last day or two of stories.

---

## 10. Adding more sources

We want many more sources than the current 34.

### The cost is not tokens

Adding sources will not blow up the AI bill, especially with a cheap
pre-filter: compare each item's embedding to the topic centroids and throw
away the obvious junk **before** anything reaches the AI. That removes most of
the volume for free.

### The cost is things breaking quietly

Every source is one more thing that can break. A feed changes format, a site
adds rate limiting, a domain expires. At 300 sources, something is broken
every single day.

What we need:

- **A health check per source**, so we know when one stops returning items.
- **Automatic quarantine.** If a source returns nothing for several runs in a
  row, disable it and raise a flag. Do not keep hammering it.
- **A dashboard** showing which sources are alive.

Dagster gives us good primitives for this (asset checks, freshness policies),
but we have to build it. It does not come for free.

There is also a legal dimension. At 300 sources, robots.txt and terms-of-service
compliance becomes a real surface, not a footnote.

---

## 11. Audio

Generating a personalized 10-minute audio brief per user per day is genuinely
expensive at 1,000 users.

**The fix is identical to the story fix:** run text-to-speech **once per
story**, then stitch each user's clips into their own playlist. Cost stays
flat as users are added.

### This constrains the audio format

Audio only stitches cleanly if **each story is a self-contained segment** with
its own beginning and end. A dialogue that flows continuously across stories
cannot be recombined per user.

**Decided by #44: a single voice, not two.** The two changes turned out to be
one decision rather than two. A two-host dialogue flows across story
boundaries and cannot be recut, which is precisely what made per-story clips
impossible, so choosing one voice is what unblocked reuse. It also resolved an
inconsistency, since decision #11 makes Norm the editor persona and two hosts
meant Norm plus an unnamed second party. Clips render lazily on first request,
because most stories are never listened to. The rework lands in M8.

---

## 12. Infrastructure

We are running two different kinds of thing and they want different homes.

| | The pipeline | The app API |
| --- | --- | --- |
| What it does | Collects, scores, writes stories on a schedule | Serves the phone app |
| Shape | Batch. Nobody is waiting. | Request/response. Someone is waiting. |
| Home | Dagster | Cloudflare Workers |

**Do not put the app API inside Dagster.** They are separate deployments.

### The app API: serverless

Cloudflare Workers plus serverless Postgres (Neon or Supabase both work well
from Workers). We already use R2 and already run a Worker for the publish
trigger (SPEC 6.11), so this is familiar ground and costs close to nothing at
1,000 users.

### The pipeline: Dagster+ Serverless, with one thing to watch

Most of the pipeline is fetching feeds and calling APIs, which is exactly what
serverless is good at.

But one step is not: **the local embedding model.** `bge-small-en-v1.5` has to
be downloaded and run on CPU, and serverless environments tend to have tight
memory limits and slow cold starts.

If that step gets slow or starts failing, the fix is **Dagster+ Hybrid**:
Dagster still hosts the scheduler and the UI, but the actual work runs on a
small machine we control. That is a configuration change, not a rewrite, which
is why starting serverless is a safe bet.

**Do not solve this by switching to a hosted embedding API.** Our cluster
threshold of 0.82 is calibrated to that specific model (SPEC 6.4), so swapping
models means re-tuning the entire clustering step. Keep the model, move the
compute if we have to.

### Budget

Dagster needs a process running all the time, unlike GitHub Actions where we
pay nothing when idle. Budget roughly $50 to $150 a month. That is fine at
1,000 users, but it is a real change from the current near-zero infrastructure
cost, so we should decide it deliberately rather than discover it.

---

## 13. Deployment and CI/CD

We are shipping two things with very different release rules.

### The backend

Normal three-environment setup in GitHub Actions:

| Environment | Deploys when |
| --- | --- |
| int | automatically, on merge to main |
| qa | on a release tag |
| prod | on manual approval |

Database migrations are gated per environment.

### The phone app

Expo gives us two ways to ship, and the difference matters:

- **Over-the-air updates (EAS Update):** JavaScript and asset changes go
  straight to users' phones. No Apple review. Minutes.
- **Full builds (EAS Build):** anything touching native code needs a new build
  submitted to Apple. Review takes days.

So "prod deploys to the App Store" is only half the story. Most changes can
ship instantly. Some cannot.

| Environment | Mobile artifact |
| --- | --- |
| int | Internal distribution build, team only |
| qa | TestFlight build, real devices |
| prod | App Store build, plus OTA updates for JavaScript-only changes |

**Run all of it from GitHub Actions**, calling the Expo CLI
(`eas build --non-interactive`, `eas update`). Not because Expo's own pipeline
is bad, but because the backend already lives in Actions and we want one place
that answers "what shipped, and when." Store `EXPO_TOKEN` as an Actions
secret.

### The thing that will actually bite us: API version skew

Once the app is on the App Store, **old versions live in the wild forever.**
People do not update. Someone will be running a six-month-old app against our
current API.

With a website we controlled both ends and could change them together. Now we
cannot.

What to do:

1. **Version the API from day one** (`/v1/`).
2. **Treat backward compatibility as a hard constraint**, not a nice-to-have.
3. **Build a minimum-supported-version check** so we can force an upgrade for
   the rare client we truly cannot support.

### App Store review notes

Apple scrutinizes news aggregators, especially around republishing other
people's content (Guideline 5.2), and around whether the app does enough to
justify existing (Guideline 4.2).

Our existing rule (paraphrase and link, never copy the original text, SPEC
decision #10) is exactly the right posture. Keep it, and be ready to explain
it in the review notes.

---

## 14. Things that will bite us later

### Dagster partitions

Partition global assets **by date**. Do **not** partition by user and date.
1,000 users times 365 days is 365,000 partitions, and Dagster handles that
badly. Keep the per-user step as one job that loops.

### Feedback telemetry

Right now "was this a good edition?" is a judgment call. With personalization
it becomes "was this relevant to *this user*?" The only way to answer that is
data: what they opened, what they skipped, what they read to the end.

**We cannot collect this retroactively.** Instrument it in v1, even before we
know how we will use it.

### Privacy and account deletion

Once we have accounts we have personal data. That means a privacy policy,
App Store privacy labels, terms of service, and a working account-deletion
flow. This is another reason personal data stays out of the data lake.

### Unit economics

| Approach | Monthly cost at 1,000 users | Per user |
| --- | --- | --- |
| Write once, reuse (this plan) | ~$150 to $350 all in | $0.15 to $0.35 |
| Write per user | $2,500+ before infrastructure | $2.50+ |

The first row supports a free tier or a cheap subscription. The second forces
us to charge real money before we have proven anyone wants the product. That
is the whole reason section 2 matters.

### What actually makes this product different

Personalized news apps are a crowded and unforgiving category. Several
well-funded ones have died.

Our differentiator is **not** the personalization. It is the thing already
built: every story rewritten in plain English at a grade 9 reading level, in a
consistent editorial voice, behind a real readability gate (SPEC decision #14,
DESIGN.md section 8). Most aggregators show a headline and a link. We show
people a story they can actually understand.

As the app gets built there will be pressure to loosen the readability gate,
skip the voice standard, or ship raw summaries to move faster. **That is the
one thing to protect.** Personalization is table stakes. The writing is the
product.

---

## 15. Decisions still open

**All five are now closed.** This table is kept as a record of what was open on
2026-08-03, and of the prediction that these were the expensive ones to defer.

| # | Decision | Closed by |
| --- | --- | --- |
| 1 | Two scores per story (`topic_score`, `general_score`) | #33, SPEC 6.4 |
| 2 | Primary plus secondary topics, replacing the single-topic field | #34, SPEC 6.4 |
| 3 | The allocator rules | #45, #48, #56, SPEC 14.4. Went a different way: the reader sets the budget and the weights |
| 4 | The audio segment format (self-contained per story) | #44, SPEC 6.7. Also settled the voice, which turned out to be the same decision |
| 5 | The fixed topic list | #49, SPEC 14.3. Ten, not 30 to 50 |

Settled already:

- Fixed topic menu for v1, custom topics later.
- Global write-once architecture.
- Users choose their own read time.
- Serverless for the app API; Dagster+ Serverless for the pipeline with
  Hybrid as the fallback.

---

## 15b. Notes on the app prototype

Observations from reading the Claude Design export in `prototypes/`, kept here
because they are about a prototype rather than about the system. **Nothing here
governs anything**, and the app's visual system is still unspecified: DESIGN.md
covers the site only.

### Where the prototype and the spec now agree

The prototype's story fields map one to one onto the story record in SPEC 14.1:
`background`, `what`, `why` and the quote fields become the `article` block.
The `flat: true` flag on stories that failed the readability gate twice is
already load-bearing in the UI, which is the same path SPEC 14.1 describes.
The archive tab is already labelled "Newsletters" rather than "Editions".

### What the prototype supplied that the spec then adopted

The weighted allocator, the five length presets, the topic weights with their
five band labels, and the whole monetization model came from reading this
prototype. It is the source for decisions #45 through #47 and part of #56.

### Things that do not survive the port to React Native

The prototype is HTML, CSS and JS. Four things in it have no direct equivalent
and need a decision when the client is built:

- **`color-mix(in oklab, ...)`** drives the per-topic tone ramps. Not
  supported in React Native. Precompute the ramp into token values instead.
- **`text-wrap: pretty`** is used on headlines throughout. No equivalent.
- **Drag to reorder topics, and the weight sliders**, use raw pointer events
  including `setPointerCapture` and `elementFromPoint`. These need
  `react-native-gesture-handler` with `reanimated`, and `elementFromPoint` has
  no analogue, so hit testing has to work from measured layout rectangles.
- **The fonts** (Newsreader, IBM Plex Sans, IBM Plex Mono) load from Google at
  runtime in the prototype. They must be bundled with `expo-font`, which makes
  them a **native** change: fonts cannot ship as an over-the-air update
  (SPEC 14.9).

The `LIGHT` and `DARK` token maps in the prototype are complete and parallel,
which maps cleanly onto NativeWind's `dark:` variant backed by CSS variables.

### Prototype features that are deliberately not in v1

- **Saved chat history.** The prototype has a past-chats list. Deferred by
  decision #54, because a stored transcript is a table of agent output and
  decision #41 forbids exactly that. The agent ships without it.
- **Free-text topics** ("name any topic and the sources attach themselves"),
  offered as a Pro benefit. Out of scope on both tiers, SPEC 14.3.
- **The Sunday retrospective.** A second assembly on a weekly cadence with its
  own AI call. Named in SPEC 14.10 and not specified.
- **The edition number.** The prototype's "No. 056" runs through the masthead,
  the push copy and the agent's opening line. Removed by decision #53: it is a
  fact about the site, not about any reader.

---

## 16. Glossary

Terms used in this document, for anyone new to the project.

**Cluster.** A group of collected items that are all about the same
real-world event. Ten outlets covering one announcement become one cluster.

**Embedding.** A list of numbers representing the meaning of a piece of text.
Texts with similar meaning produce numbers that are close together, which is
how we group stories without matching exact words.

**Bronze / silver / gold.** The three stages of our data lake. Bronze is raw
collected items. Silver is cleaned and enriched (deduplicated, clustered,
scored). Gold is long-term history.

**Iceberg.** A table format that sits on top of files in cloud storage. It
gives us safe appends, partitions, and the ability to read past versions.

**Dagster.** An orchestrator. It decides what pipeline step runs when, tracks
whether each step succeeded, and lets us re-run pieces.

**Deterministic code.** Ordinary code that produces the same output for the
same input every time. The opposite of an AI call. Our rule zero says AI makes
judgments and deterministic code does everything else (SPEC section 2).

**Allocator.** The new deterministic component described in section 7. It
decides which stories go into a given user's newsletter.

**EAS.** Expo Application Services. The build and update service for Expo
apps.

**OTA update.** Over-the-air update. Shipping new JavaScript to phones without
going through App Store review.

**Prompt caching.** Reusing the unchanged front portion of a prompt across
calls. Cached input costs about a tenth of normal input.

**Batch API.** Submitting many AI requests at once and accepting results
within a few hours instead of seconds. Costs 50% less.

**Serverless.** Infrastructure where we do not manage a machine. We deploy
code and the platform runs it on demand.

**Partition.** A slice of a table, usually by date. Partitioning lets a job
process or replace one day without touching the rest.
