# landing/

The marketing landing page for the **app**. React, Vite and Tailwind v4.

## What governs this

**Nothing yet, and that is the point of this note.**

Under CLAUDE.md rule 1, a behavior not covered by SPEC.md or DESIGN.md needs a
proposed spec addition before it is implemented. This page has no such
coverage:

- **DESIGN.md is the site's design system, not the app's.** CLAUDE.md lists
  "the app's visual system" under *Not yet specified*.
- **The stack is not the site's stack.** The site is Astro with zero client
  JavaScript except the two scripts named in DESIGN.md section 7. This is a
  React SPA. It is a second front end in a repo that had one.
- It **deploys to `norm.news`**, the app's own domain, and still has no spec
  section. This used to read "not wired to any deploy", which was part of why an
  unspecified page was acceptable. That defence is gone; the page is public.
  `astro.config` is still untouched and the Astro site still publishes to GitHub
  Pages, so rule 6 is unaffected. Two files name the domain and no others:
  `index.html`, whose Open Graph tags have to be absolute, and `wrangler.toml`,
  which holds the origin the confirmation email loads the mug from. No source
  file contains it.
- **It now holds personal data**, which nothing else in this project does. The
  waiting list is a real database with real email addresses in it, and that
  reaches decision #36 and section 14.12 rather than only the design.
  `PROPOSED-SPEC.md` in this directory is the addition it owes, and it is the
  one gap here worth closing before the others.

It lives in the repo because it is worth keeping and iterating on, not because
it has been approved. Treat it as a working draft until a spec section covers
it.

## Where the design came from

Tokens are lifted from `prototypes/ds/foundations/` verbatim: paper `#f6f4ee`,
ink `#23231f`, oxide `#3f6a50`, Newsreader with IBM Plex Sans and Mono.

Two sections are ports of real prototype screens rather than new design:

| Section | Source |
| --- | --- |
| Topics | `prototypes/App Interface.dc.html`, More → Topics. Data tables (`NS_TOPICS`, `NS_BANDS`, `NS_INKS`, `NS_LEN`), copy and pixel values are the prototype's |
| Norm | `prototypes/App Interface.dc.html`, the chat. Mug SVG, steam keyframes, `THINK` phrases and `EXCHANGES` are the prototype's |
| Shared-link card | A supplied image, `public/og.png`, 1200x630: the mug and the Norm wordmark on `#ddd9cc`. Nothing generates it. It previously ported `site/public/og-default.svg` via `npm run og`, and that generator was removed so it cannot overwrite the real card |

`public/favicon.svg` and `favicon.ico` are byte copies of the site's. The mug is
one glyph across both front ends (DESIGN.md section 10), so it is copied rather
than redrawn. `scripts/build-og.mjs` borrows resvg from `site/node_modules` for
the same reason: a second copy of that pipeline is how the two front ends drift
apart. It now renders only `apple-touch-icon.png`, which is pure paths and needs
no text measurement, so the satori step and the font loading it required are
gone along with the card generator.

Two deliberate divergences from the prototype in that ported copy, both
required by CLAUDE.md rule 7: a section with nothing in it today reads `none`
rather than the prototype's em dash, and the two ported sentences that carried
an em dash are punctuated with a full stop instead.

The hero video is a recording of the committed prototype, walked end to end.

## The waiting list

The Coming Soon form is the only thing on the page that is not a page. It posts
to `functions/api/subscribe.js`, a Cloudflare Pages Function, which writes the
address to a D1 table (`schema.sql`) and sends one confirmation through Resend.

Three things about it are deliberate and are each one edit away from being
undone:

1. **The row is written before the mail is sent, and a failed send still
   returns success.** The signup is what cannot be lost; the confirmation can be
   sent again. A null `emailed_at` is how a failed one stays visible.
2. **A duplicate address sends nothing.** `email` is the primary key and the
   insert is `ON CONFLICT DO NOTHING`, so one address receives at most one
   message from the endpoint ever. That is what stops a public form that sends
   email being a way to mail a stranger repeatedly.
3. **The address is never logged.** Failures record the Resend status and not
   the recipient, because Cloudflare's logs are not one of the places a deletion
   request can reach.

Reading it:

```
npm run waitlist              # CSV to stdout, count to stderr
npm run waitlist > list.csv
npm run waitlist -- --local   # the copy `npm run dev:api` writes to
```

There is no HTTP read path. `subscribe.js` exports `onRequestPost` and a 405 for
everything else, so seeing the list needs an authenticated Cloudflare account.

`PROPOSED-SPEC.md` is what this owes SPEC.md. It matters more than the page's
other gaps, because this is personal data rather than a design decision, and it
carries the one hard rule: **nothing is broadcast to this list until a real
unsubscribe exists.** The confirmation is transactional and reply-based removal
is enough for it. A launch announcement is marketing and is not the same thing.

The composing floor in The overnight run is new work rather than a port. It
reads the same `stage` the numbers do, and its four states are the physical
version of the pipeline: copy lands on the stone, duplicates stack behind a
lead, the survivors lock into a forme as lines of type. Every slip is the same
240x3 block and only its transform changes.

## Things a reader should not mistake for spec

- **The hero says tracked stories shape the newsletter.** SPEC 14.8 opens by
  making the tracker a side branch that "is never part of assembling or
  delivering a newsletter", and the allocator in 14.4 reads topics and weights,
  not tracked stories. The copy was given directly and is used verbatim. It is
  recorded here so it is not read back as a requirement.
- **The overnight run says the collector runs every hour.** SPEC 6.2 sets it at
  every three hours, `collect.yml` runs `cron: "7 */3 * * *"`, and
  `pipeline.yaml`'s `since_window_hours: 6` is sized for that cadence. Hourly
  is the app's intended design, given directly. The four figures beside it are
  measured rather than projected: 35 is the enabled count in
  `config/sources.yaml`, 149 and 112 are per-day means over the 17 published
  editions, and 5 to 20 is the reader's length setting.
- **The Norm section no longer shows the tracker at all.** It previously
  carried a coverage chart designed from spec text alone, with no reviewed
  design artifact behind it. The chart, its watch button, and the bullet that
  described the behavior have all been removed.
- **There is deliberately no past-chats list.** Decision #54 defers it and #41
  forbids storing agent output. The prototype shows one; it is not adopted.
- **The page names no price, no plan and no tier.** It is a waiting list, and
  SPEC 14.10's tier table is not settled enough to sell from. Any future
  pricing block is a copy decision that has to be checked against 14.10 rather
  than lifted from the prototype's plan screen, which governs nothing.
- **The footer commits the project to a use limitation.** It states that a
  subscriber's address is used only for updates about Norm's Newsletter and is
  never sold, shared, or used to advertise. That is true of the code as written
  and it matches what the form and the confirmation mail already promise, but no
  spec section carries it, so nothing enforces it either. It is a promise the
  page makes on the project's behalf. `PROPOSED-SPEC.md` question 4 is where it
  has to be honoured, and question 3's rule still stands: the first broadcast to
  this list is marketing and needs a real unsubscribe before it is sent.
- **The footer states no retention period, deliberately.** `PROPOSED-SPEC.md`
  question 2 records that there is not one yet. A footer is not the place to
  invent policy, so it is the one thing the legal line is missing rather than
  something that was overlooked.

## Running it

```
cd landing
npm install
npm run dev          # http://localhost:5201, no Functions
npm run dev:api      # http://localhost:8788, builds first, Functions included
npm run icon         # regenerate apple-touch-icon.png only (rarely needed)
```

`npm run dev` serves the page without the Function behind it, so the Coming Soon
form lands in its error state. That is correct rather than broken: nothing was
recorded, so the form has to stay. Use `npm run dev:api` to exercise the real
endpoint, and set up its local database once with

```
npx wrangler d1 execute norm-waitlist --local --file=schema.sql
```

`DEPLOY.md` in this directory is the start-to-finish guide for `norm.news`:
the DNS move, the Cloudflare Pages setup, the waiting list's Resend and D1
setup, and the one-command loop for shipping a change afterwards.

`public/view.html` is a development harness, not a page: it frames the site at
1440, 900 and 390 side by side so responsive behavior can be checked in one
view. `window.setW`, `setFrameScroll` and `scrollAll` are available on it.

Note that Chrome suspends rendering in hidden tabs, so the hero video, the
scroll reveals and the composing floor will all appear stuck if the tab is not
visible. That is the browser, not the page.
