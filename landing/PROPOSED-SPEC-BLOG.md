# Proposed spec addition: the blog

**Status: a proposal. It governs nothing.** Under CLAUDE.md rule 1 this should
have been written and approved before the code it describes. It was not, and
this one is worse than the other two: the code was written, merged and deployed
to production first, on 2026-08-28, with the gap noted in the pull request
rather than closed before it. `PROPOSED-SPEC.md` and `PROPOSED-SPEC-DISCOVERY.md`
in this directory open the same way, for the same reason, about the waiting list
and about machine readability.

Those two files split `landing/`'s spec debt along a clean line: one is about a
table of other people's email addresses, the other is about what a machine sees
when it fetches the page. This is a third thing. It is about the domain
publishing **writing**, which is what the rest of this project exists to do, and
which nothing in `landing/` did until now.

`PROPOSED-SPEC-DISCOVERY.md` closes with the sentence this document is here to
answer:

> `/blog` ships with no posts and says so, which is the test of the distinction.

It no longer ships with no posts, so the test has been taken. What follows is
what the thing turned out to be.

---

## What exists today

One post, at `/blog/put-my-phone-down`, published 2026-08-28. An index at
`/blog` listing it. Measured after the deploy on that date:

```
$ curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://norm.news/blog
200

$ curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://norm.news/blog/put-my-phone-down
200
```

Neither is a redirect, which settles the one thing the build could not prove:
`dist/blog.html` answers `/blog` and `dist/blog/put-my-phone-down.html` answers
the post, and the two do not collide because there is no `blog/index.html`.

The post is 801 words of first-person prose by a named person. It is the first
thing on this domain that is neither product copy nor Norm speaking.

The pieces:

| File | What it holds |
| --- | --- |
| `src/blog-content.js` | `POSTS`, the only place the copy is written |
| `src/BlogPage.jsx` | the index, one card per entry in `POSTS` |
| `src/PostPage.jsx` | the post, which names its own slug |
| `blog/put-my-phone-down.html` | the post's document: title, description, canonical, Open Graph |
| `src/main-post.jsx` | the post's client entry |
| `vite.config.js`, `scripts/prerender.mjs` | one input and one `PAGES` entry per document |

## Proposed: SPEC 15.5 and 15.6

`PROPOSED-SPEC-DISCOVERY.md` proposes section 15, *The landing page*, with
subsections 15.1 to 15.4. These two continue it and depend on 15.1 being
adopted, because everything below is an application of its contract.

### 15.5 What a post is

**A post is a record in a copy module, not a file format.**

There is no markdown, no front matter, no content directory and no CMS. A post
is an entry in `POSTS` in `src/blog-content.js`, and adding one is editing that
array. The fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `slug` | string | URL segment, and the post's identity. Never changes after publication |
| `title` | string | The headline. Not the document title, which appends the site name |
| `dek` | string | The standing subtitle. Also the page's meta description, so it has to work read alone |
| `date` | string | ISO 8601 date, the publication date |
| `dateLabel` | string | The same date as a reader sees it |
| `author` | string | A person's name |
| `minutes` | number | Stated reading time |
| `body` | array | Blocks, in order, each `{ kind, text }` |

`kind` is one of `text`, `pull` or `close`. The page sets the three differently
and nothing in the copy carries a class name, which is what keeps this file
readable as prose rather than as markup.

**Three consumers read this file and none of them get a second copy of the
words.** The pages render it, the JSON-LD is composed from it, and `llms.txt`
lists it. That is the same rule 15.3 sets for the FAQ and the front page, and it
exists for the reason `faq-content.js` records: a hand-maintained copy of text
that changes is a copy that stops being true, and nothing in the build would
catch it.

**Every block's `text` is machine-readable copy.** Structured data and `llms.txt`
read `text` regardless of `kind`, so the words a crawler receives are the whole
post rather than a subset. A block kind is a typographic instruction, never a
way to hide a sentence from a machine.

`dateLabel` is stored rather than formatted from `date` at render time. That is
deliberate and it is a small piece of duplication: a formatter is a locale
decision, and this project has exactly one locale and one date to render.

### 15.6 Where a post lives

**One post is one prerendered document at `/blog/<slug>`.**

Decision #60 already settles that a second page on the landing site is a
document rather than a client route, and that the practical form is a top-level
`faq.html` rather than `faq/index.html`, because Pages serves the former at
`/faq` directly and makes the latter a redirect. A post extends that by one
step: the index keeps the top-level form at `blog.html`, and posts sit in a
`blog/` directory beside it. `/blog` is therefore not a directory index and does
not redirect, which is verified above.

The cost is that a post is **five edits, not one**: the record, the document,
the client entry, the Vite input and the `PAGES` entry. That is a real price and
it is the price of 15.1. A client-side route would make a post one edit and
would break the contract for every reader that is not a browser.

**This is fine at one post and wrong at twenty.** The proposal is to pay it
until the count makes it untenable and then generate the four mechanical pieces
from `POSTS` rather than to reach for a router. The contract is about what
arrives in the response body; nothing in it requires a human to type the
scaffolding. When that day comes, `PAGES` already maps over `POSTS`, which is
the half that was written to anticipate it.

**Each document's byte floor rises with its content.** The prerender asserts a
minimum markup size per page and fails the build otherwise, because an empty
root is indistinguishable from a working build without fetching production
(decision #57). `/blog` is 3,000 and a post is 6,000.

## The four questions this owes an answer to

### 1. Does the voice standard apply to a post?

This is the substantive question in this document and it has no obvious answer.

DESIGN.md section 8 opens: *"Applies to every word the pipeline generates:
glance, summaries, articles, briefly lines, audio script, notice banner."* Every
clause under it is written for machine output. Clause 7 asks for neutral and
calm, no hype words, no political editorializing, and says *"Norm reports what
sources reported."* Clause 5 requires every story to answer what happened and
why a normal person should care. Clause 9 governs quotes from sources. A
first-person essay about why somebody built a thing satisfies none of these and
should not have to.

CLAUDE.md complicates it: *"DESIGN.md does not yet cover the app's visual
system, and the voice standard applies to both."* That sentence is about the
site and the app, both of which publish pipeline output. It was not written with
a human byline in mind.

Recommendation: **the voice standard governs generated text, and a post is not
generated text.** Two things still bind, and they bind for different reasons:

- **CLAUDE.md rule 7, no em dashes.** That rule is explicitly wider than the
  pipeline: *"in any generated text, prompt file, code comment, or user-facing
  copy."* A post is user-facing copy. This is a hard rule.
- **Plain English, as an aim rather than a gate.** The readability gate is a
  build step that runs on an edition and holds it to grade 9. Nothing runs on a
  post and nothing should. The reason the gate exists, that a smart friend
  outside the industry should be able to read this, is worth keeping as an
  intention.

If this recommendation is wrong, the correction is not to run the gate over the
post. It is to say that the domain does not publish first-person writing, which
is a larger decision than a style rule.

### 2. Who is the author, and does the domain say "I" now?

Everything else on `norm.news` speaks as the product or as "we". The footer
credits a person, and the FAQ answers in the product's voice. A post has a
byline and says "I".

That is the point of it, and it is worth stating so it is a decision rather than
a drift: **the blog is one person writing about building the thing, and it is
the only place on the domain where that voice is used.** A post signed by Norm
would be the AI editor writing about its own creation, which is a different and
much stranger product than the one being built.

The practical consequence is that `author` is a real person's name in the
`BlogPosting` markup, and it is the first personal name this project publishes
in structured data. That is the author's own name on their own site, which is
not the kind of personal data `PROPOSED-SPEC.md` is about, but it is worth
noticing that the two documents now both touch a person.

### 3. Does publishing a post mail the waiting list?

**No, and this is the trap `PROPOSED-SPEC.md` already named.**

That document's question 3 concludes: *"Nothing should be broadcast to this list
until that exists"*, where "that" is a real unsubscribe with a one-click link, a
`List-Unsubscribe-Post` header and a suppression list that outlives the row.

A blog post is exactly the thing that makes somebody want to send the first
broadcast. It is new, it is good, and the list was collected from people who
said they were interested. None of that changes what the message is: a mail sent
to everyone at once about a thing the sender made is marketing, and the
confirmation's reply-based removal is not sufficient for it.

**Publishing a post is not a reason to mail the list.** If a post should reach
the list, the unsubscribe comes first, and it is the same unsubscribe the launch
announcement needs.

### 4. What happens when a post is edited?

Nothing today. `dateModified` in the `BlogPosting` is set to `datePublished`,
because there has been no modification and claiming one would be describing
something that did not happen, which is the same instinct decision #59 encodes.

Proposed: **a typo fix is silent, and a change of meaning gets a
`dateModified` and a line in the post saying what changed.** The distinction is
whether a reader who read the old version would be misled by not knowing. That
is a judgement, and it is the right kind of judgement to leave to a person on a
blog with one author.

A `slug` never changes after publication. The URL is the post's identity and
somebody may have linked to it, which is the whole reason the domain exists.

## Proposed decisions

For SPEC section 10, which currently ends at #56, and which
`PROPOSED-SPEC-DISCOVERY.md` proposes taking to #61.

| # | Decision |
| --- | --- |
| 62 | A blog post is a record in a copy module rather than a file in a content format. There is no markdown, no front matter and no CMS. The page, the structured data and `llms.txt` all compose from that one record, so the words a crawler receives and the words a reader sees cannot drift, which is the rule 15.3 already sets for the rest of the landing page |
| 63 | One post is one prerendered document at `/blog/<slug>`, and the index stays a top-level `blog.html` so `/blog` resolves without a redirect. This extends decision #60 rather than replacing it. A post costs five mechanical edits, which is the price of the 15.1 contract; when the post count makes that untenable the scaffolding is generated from the post list, never replaced by a client-side route |
| 64 | The voice standard governs text the pipeline generates, and a blog post is not that. A post is one person writing under their own name, and it is the only first-person voice on the domain. CLAUDE.md rule 7 still binds it, because that rule covers all user-facing copy; the readability gate does not, because a gate is a build step for an edition and nothing runs over a post |
| 65 | Publishing a blog post is never a reason to mail the waiting list. The first message sent to everyone at once is marketing whatever its subject, and `PROPOSED-SPEC.md` question 3 already requires a real unsubscribe before any such send. A post is the most tempting occasion for that mistake, which is why it is written down here rather than left to judgement |

## Proposed addition to section 11

Under the non-app-layer questions:

- Whether the blog gets a feed. The site publishes `feed.xml` for editions and
  a podcast feed for the audio, and a blog with a feed is the ordinary shape of
  the thing. It is not proposed here because one post is not a feed, and
  because a feed is a second machine-readable surface with its own correctness
  question, which is 15.3's territory rather than this document's.
- Whether a post gets its own Open Graph image. Today every page on the domain
  shares `og.png`, so a post shared anywhere shows the product card rather than
  the post. The site already generates a per-edition card with satori, so the
  technique exists in the repo. It is a discovery question and belongs beside
  the others.

## What this does not cover

Recorded so that this is not read as closing rule 1's gap for `landing/`.

- **The blog's visual system.** DESIGN.md is the site's design system. The
  post's typography borrows from it deliberately, the story cards on the index
  are built on the shape section 4 gives `StoryCard`, and the reading column is
  the 720 pixels section 3.3 sets, but borrowing is not coverage. The app's
  visual system remains unspecified and this does not change that.
- **The claims a post makes.** `README.md` records the things the pages say
  that the spec does not carry. A post is prose about the author's own
  experience rather than a product claim, but the line is not perfectly clean:
  the first post describes what Norm will be able to do, and that is a claim.
  It stays flagged in `README.md` with the others.
- **Whether the domain should carry the edition archive instead.**
  `PROPOSED-SPEC-DISCOVERY.md` closes on this and it is untouched. A blog is
  not an answer to it. The archive is real writing that already exists and
  putting it on `norm.news` remains the largest thing that could be done for
  discovery.

## What is deliberately absent

- **No tags, no categories, no archive by month.** One post. Every one of those
  is a page that exists to hold a list, and thin pages written for a crawler
  are the technique the voice standard exists to prevent.
- **No comments.** A comment surface is a third place holding other people's
  words on this domain, after the waiting list, and it would need a moderation
  policy and a deletion path before it needed a design.
- **No author page.** There is one author and the footer already names him.
- **No reading-time computation.** `minutes` is stated by the author rather
  than derived from a word count, because a derived number is precise about
  something nobody measures that way. If it ever drifts far enough from the
  truth to matter, deriving it is four lines and the field does not change.
- **No draft state.** A post in `POSTS` is published. Anything unfinished lives
  outside the repository until it is not, which is the same reason there is no
  CMS: a draft system is a feature for people who publish on a schedule, and
  this one publishes when there is something to say.
