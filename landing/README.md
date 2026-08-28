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
  React SPA. It is a second front end in a repo that had one. It is now
  prerendered, so the served HTML holds every word of the page, but the words
  are still painted by React in the browser.
- It **deploys to `norm.news`**, the app's own domain, and still has no spec
  section. This used to read "not wired to any deploy", which was part of why an
  unspecified page was acceptable. That defence is gone; the page is public.
  `astro.config` is still untouched and the Astro site still publishes to GitHub
  Pages, so rule 6 is unaffected. Five files name the domain and no others:
  `index.html`, `faq.html` and `blog.html`, whose Open Graph tags and canonical
  links have to be absolute, `wrangler.toml`, which holds the origin the confirmation email
  loads the mug from, and `scripts/prerender.mjs`, which holds the `SITE_ORIGIN`
  that robots.txt, sitemap.xml, llms.txt and every JSON-LD graph derive from.
  A page's own `.html` names the domain because the format demands it; anything
  generated derives it. No component file contains the origin. `App.jsx` carries `norm@norm.news` in the footer and in
  a form error, which is a contact address rather than a URL and does not move
  if the domain does.
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
| Hero slideshow | `prototypes/App Interface.dc.html`, six screens captured from the running prototype. See **The hero slideshow** below |
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
an em dash are punctuated with a full stop instead. The hero slideshow below
carries the same divergence a third time, for the same reason.

## The bar and the headline

**The bar runs the full width of the window; everything under it holds
1140px.** `.site-header-row` is capped at 1600px rather than 1140px, so the
wordmark sits out at the left margin and the nav at the right one instead of
both pulling into a column with a quarter of the screen empty either side. The
cap is there for a very wide monitor, where an unbounded bar puts its two ends
too far apart to read as one object.

**The wordmark is the mug and the word together.** The glyph is
`public/favicon.svg`'s drawing, not the animated `Mug` the Norm section uses:
the same three steam curls, handle and body, with `currentColor` in place of
the hard-coded ink so it follows the palette and rides the bar's entrance with
the letters. DESIGN.md section 10 wants one mug across both front ends, and
the favicon is where that mug lives. Nothing about it moves. The steam is
drawn, not breathing.

It sits inside the `/` link rather than beside it: one target, one hover, one
entrance, and a click on the cup goes home like a click on the letters. The
svg is `aria-hidden`, so the link's accessible name is still "Norm" rather
than the mark read out twice. The hover underline moved off the link and onto
the word, because on a flex container the line runs the width of the box and a
rule under the cup reads as a mistake rather than as a hover.

**Its size and place come off a drawing of the mark**, measured and divided by
the cap height so they hold at any font size: the ink is 1.71 cap heights tall
and stands 0.64 of one clear of the N, with the bottom of the cup on the
baseline the letters stand on. Newsreader's cap is 0.676em, which is where
`height: 1.2em` and `gap: 0.37em` come from, trued against a screenshot of the
rendered bar because the svg's box is a little larger than the ink in it. The
alignment is `align-items: baseline` and nothing else: a flex item with no text
of its own takes its bottom edge as its baseline, and `MugMark`'s viewBox is
cropped to end at the bottom of the cup, so the two meet with nothing to nudge.

**It changes colour as one mark, and that took a rule.** The glyph and the
letters are both children of the link now, every path in the mug takes
`currentColor` from the svg above it, and `.tod *` gives every element on the
page a 900ms colour transition of its own. So each of them was easing towards
its parent's colour on its own clock while the parent was already moving: the
bar's 700ms entrance walked the link up out of the paper and the cup, the
handle, the steam and the letters each arrived after it, at slightly different
times. It was visible on a cold load as a mug turning up late to its own word.
`transition: none` on the link's descendants fixes it: with no clock of their
own they track the link exactly, frame for frame, through the entrance and
through the delivery dial afterwards. The only colour transition left in the
wordmark is the one on the link.

Both copies of the wordmark get it, the bar's and the phone sheet's, and so do
`/faq` and `/blog`, which draw the same `Header`.

**The bar has its own gutter above 900px, and it is the only rule that
overrides `.pad-x`.** `clamp(2.5rem, 6vw, 7rem)` there, against the page's
`clamp(1.25rem, 4vw, 2.5rem)` everywhere else: 54px of margin at 900, 98px at
1633, and past about 1720 the 1600px cap takes over and the margin is whatever
is left over. The two ends of the bar are the only things on the page that
ever reach the edge, and at the page's own 2.5rem they sat on it.

The extra margin is a breakpoint rather than a wider clamp at every size, and
that is the whole reason for the 900px. On a phone the wordmark in the bar
sits directly over the copy below it, so a bar with a gutter of its own would
put the two a few pixels out of line. Below 900 the bar takes the page's
gutter exactly.

**The hero holds the same 1140px column** it always did, top aligned under the
bar, with the copy and the slideshow spaced as they were. The bar being wider
than the content under it is deliberate.

The one measurement that moved is the gap under the bar: `lg:pt-16` above
1024px, 64px rather than 40px, so the eyebrow reads as the top of a page
rather than as a line hanging off the bottom of the nav. It is a step at 1024
rather than a fourth value on the ramp, because a smaller window is short as
well as narrow and there the 40px is the right gap. The 24px comes out of the
slack the phone figure already had: the caption still clears the fold at 1920
by 1080, 1633 by 755, 1440 by 900, 1366 by 768, 1280 by 800, 1152 by 700 and
1024 by 640.

**The headline ceiling is 88px, up from 74px.** The slope is the same `5.6vw`,
so nothing under 1320px changes; past that a large display gets a masthead
rather than a headline that stopped growing while the window kept going. Both
lines still hold without ragging at every size the clamp reaches, which is the
constraint that decides the ceiling: the break is the point of the line.

## The hero slideshow

Six stills of the app, five seconds apart, each with one sentence under it.
They replaced a looping video of the same prototype, which played one fixed
walk that nobody could stop or steer and never said what was being shown. The
video and its poster are deleted rather than left in `public/`, where they
would have kept deploying with nothing referencing them.

Four ways to move between them, and a rule about the timer.

- **Swipe or drag** the phone. `touch-action: pan-y`, so a vertical swipe still
  scrolls the page. `.ns-grip` further down records what happens when a
  full-width region swallows the whole gesture instead.
- **Dots** under the phone. Always visible, because they are also the only
  thing that says how many screens there are and which one this is.
- **Arrows** inset at the left and right edges, revealed when a pointer is over
  the phone and hidden again when it leaves. Behind `@media (hover: hover)`, so
  a touch device never carries two buttons it cannot reveal, and repeated on
  `:focus-visible`, because a keyboard never hovers and would otherwise put a
  focus ring on something invisible.
- **Arrow keys**, once the slideshow has focus.

The dots, the arrows, the keys and the timer all **wrap**. A drag does not: it
is clamped with resistance at both ends. Direct manipulation is bounded so a
thumb pushing against nothing feels the end of the track, and the indirect
controls cycle.

**Any of them stops the timer for good.** Not paused, stopped. Once a reader
has chosen a screen, nothing should slide it out from under them mid-sentence.

**The shading is a `box-shadow` on the carousel box, not on the images.** It
was a `drop-shadow` filter on each `<img>` first, and that was a bug worth
recording because it did not look like one: `.phone-slides` carries
`overflow: hidden` and its box is exactly the image box, so the filter was
clipped away in full and the hero had no shading at all, in any palette, while
the declaration sat there in the DOM looking correct. `overflow` clips an
element's descendants but never its own `box-shadow`, so moving the shadow onto
the clipping box is the whole fix. The phone is a rounded rectangle, so a
`box-shadow` on a matching `border-radius` is the exact silhouette and there is
no rectangle for the shading to fall back into. The radius is `11.94cqw`, the
prototype's 48px corner over its 402px device width, which also makes the clip
agree with the image's own alpha corner to within a hundredth of a pixel.

**The shadow is a palette token, `--phone-shadow`.** Four of the five papers are
light and take black at 30 to 38 percent. Night paper is `#1a1a17`, where that
is invisible, so it takes black at 60 percent with a shorter throw: on a
near-black ground a wide soft shadow dissolves, and a tighter one reads as the
phone sitting on the page. The 900ms transition is scoped to `.phone-slides`
rather than added to the blanket `.tod *` rule, which carries only background,
colour and border.

**There is no attribution line under the caption.** It read
`From the app · No. 074` and was removed. The record of which edition the
stills are still belongs somewhere, and that somewhere is this file.

**Its width comes from the height going spare, not from a fixed cap.** At a
flat 324px the phone stood 704px tall, and with the dots and the caption under
it the figure ran off the bottom of any laptop: the screen and the sentence
describing it could not be on show at once. `.phone-slides-figure` derives the
width from `100svh` instead, capped at 324px and floored at 210px, so it is
324px on a tall display and about 250px on a 800px one. Only above 900px,
which is where the hero is still two columns. The caption is deliberately
wider than the phone and centred on it: held to the phone's width it wrapped
to two lines on a short window, and those cost more height than the narrowing
saved.

| File | Screen | How it is reached in the prototype |
| --- | --- | --- |
| `app-today.webp` | Today | the default state |
| `app-listen.webp` | Listen | the `Listen to today's brief` row on Today |
| `app-story.webp` | Story | `Read the full story` on a **grounded** story. Most are not: an ungrounded one shows a `NOT WRITTEN UP` notice instead of the background, what happened and why it matters that the caption promises |
| `app-archive.webp` | Archive | the Archive tab |
| `app-topics.webp` | Topics | More, then Topics |
| `app-norm.webp` | Norm | the round mug button, one question asked. **Leave `Past chats` closed**: decision #54 defers it |

They are edition No. 074 and are regenerated from `prototypes/` when that
export next changes. The procedure, because nothing in the build does it:

1. Copy `prototypes/` somewhere scratch and edit **that copy only**, per the
   divergences below. Serve it over HTTP; `file://` silently shows placeholder
   data. `.claude/skills/render-prototype` is the rest of the procedure.
2. The device is one element, 402x874 with a 48px radius. Scale it by 1.5 with
   `transform` and pin it to the top left, then capture two viewport tiles and
   stitch them. A screen shorter than 874px is why: the browser screenshot
   comes back at CSS resolution, so the only way to more pixels is to make the
   device occupy more of them.
3. Crop each tile to the device's measured rect, stack to 603x1311, mask the
   corners to transparency at radius 72, and encode WebP. Six files, about
   300 KB against the video's 1.5 MB. The transparent corners are what let the
   page show through them; the shading is separate and is described below.

**Three divergences from the prototype, in the scratch copy only.** The
committed `prototypes/` keeps the prototype's own strings.

1. The Today screen's audio label reads `Norm reads it` rather than the
   prototype's `Two hosts`. SPEC decision #44 supersedes the two-host format,
   and a public page should not advertise one that is already replaced.
2. Six sentences that carried an em dash are punctuated with a full stop.
   CLAUDE.md rule 7, the same divergence already recorded above for the ported
   copy. A screenshot is user-facing copy like any other.
3. `Swipe down. Keeps playing` for the same reason, in the player sheet.

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

## What a machine sees

`npm run build` runs `vite build` and then `scripts/prerender.mjs`. The second
step is why the served HTML is not empty.

Until 2026-08-24 the page shipped 3,166 bytes and an empty root div. Every word
arrived from React at runtime, so Google saw the page and almost nothing else
did: not Bing, not a reader-mode parser, not any crawler that feeds a language
model. `prerender.mjs` renders the app to static markup at build time and writes
it into `dist/index.html`, which is now about 36 KB with the `<h1>` in it, and
into `dist/faq.html`, which holds all ten answers whether or not anything ever
clicks to open them.

Four things follow from that one step, and all four are `dist/` only. Do not
look for them in `public/`.

| File | Where it comes from |
| --- | --- |
| `robots.txt` | Written by the script. Cloudflare merges its own managed block into it at the edge, so the served file is not this file |
| `sitemap.xml` | Written by the script, one entry per page in `PAGES` |
| `llms.txt` | Composed from `App.jsx`'s exported copy constants and `faq-content.js`, so it cannot drift from the pages |
| JSON-LD | Injected into each head. `/` gets `Organization` + `WebSite` + `WebPage` + `SoftwareApplication`; `/faq` gets `FAQPage` + `BreadcrumbList` and references the first two by `@id` |

Three things about it are deliberate.

1. **React re-renders over the markup rather than hydrating it.** `main.jsx`
   still calls `createRoot().render()`, which replaces the container's children.
   Switching that to `hydrateRoot()` would turn every future edit into a
   server and client matching problem for no gain on a static page.
2. **The build fails rather than shipping an empty page.** The script asserts
   the markup exists and clears a size floor. The failure mode here is silent:
   an empty root looks exactly like a working build until somebody runs `curl`
   against production, which is how the page sat that way unnoticed.
3. **`index.html` carries a `<noscript>` rule.** Everything on the page starts
   at `opacity: 0` and is revealed by script, so prerendering alone produces a
   document that is complete and invisible. The rule restores it for a visitor
   without JavaScript. The interactive parts render and do nothing.

Fonts are self-hosted through `@fontsource`, the same three families the site
imports in `site/src/styles/global.css`, at the weights this page actually uses
(400 and 500, upright, no italic). The page now makes no third-party request at
all.

`DISCOVERY-SETUP.md` is the operator guide for the two halves of this that are
not in the repo: the Cloudflare crawler policy, and registering the site with
Google and Bing. Neither can be done from here.

`PROPOSED-SPEC-DISCOVERY.md` is what this owes SPEC.md, and it is the second
proposal in this directory rather than an extension of the first. It also
records the crawler question, which is worth knowing before reading
`robots.txt`: Cloudflare blocked the major AI crawlers on this zone by default,
nobody chose that, and it was turned off in the dashboard on 2026-08-24. The
served file is now the one this build writes. Shipping a `robots.txt` is not
what removed the block and could not have been.

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
- **The hero's archive caption says searchable, and so does the FAQ.**
  "Every edition Norm has filed, kept and searchable" is slide four's sentence.
  The prototype's Archive screen does carry a search box, but SPEC 14 specifies
  no archive search, per the next entry. The claim is now in two places and the
  two have to move together, the same way the hourly collector figure does.
- **The FAQ says the archive stays searchable.** "Length changes the paper, not
  the archive. Everything Norm has ever filed stays searchable" is in the answer
  about changing topics and length. SPEC 14 specifies no archive search: 14.4
  assembles a newsletter and 14.7 is the app API, and neither carries a query
  over past editions. The copy was given directly and describes intended
  behaviour. It is the newest thing on either page that the spec does not carry.
- **The FAQ says "add a new section any time".** That means choosing from the
  topics the app offers, which is what `TopicStudio` demonstrates. It does not
  mean free-text topics, which 14.10 explicitly defers along with the Sunday
  retrospective. The sentence is fine as long as nobody reads it as a
  requirement for the deferred feature.
- **The FAQ restates the hourly collector figure.** Same divergence as the
  overnight run above, in a second place now: SPEC 6.2 and `collect.yml` say
  every three hours. The two sentences have to move together if that figure is
  ever corrected, and both are in copy given directly.
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

## The FAQ copy

`src/faq-content.js` is the only place the questions and answers are written.
Four things read it: the homepage teaser (the five items flagged `teaser`), the
`/faq` page, the `FAQPage` structured data, and the "Common questions" block in
`llms.txt`. The last two are composed from those strings at build time rather
than restated beside them, for the same reason `llms.txt` is composed from the
page's copy constants: a second copy of text that changes is a copy that stops
being true, and nothing in the build would catch it.

So a copy edit happens in that one file. Two things about it are worth knowing
before editing:

- **The answers are plain strings, not JSX.** They are rendered as React text
  children, where an HTML entity would appear literally, so the curly quotes and
  apostrophes are real characters. It is also what lets the same string go into
  JSON-LD and a plain-text file untouched. Where an answer needs a link, the item
  carries a `link` and the renderer turns that one substring into an anchor.
- **No em dashes.** CLAUDE.md rule 7. The supplied copy carried eleven and each
  one is a full stop or a comma here, which is the same divergence already
  recorded for the empty-section label and the two ported sentences.

The answers are also in the markup at every state, collapsed by CSS rather than
by React. That is the point of the page and it is one edit away from being
undone: see the comment at the top of `src/Accordion.jsx`.

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

`DEPLOY.md` in this directory is the one-time setup for `norm.news`: the DNS
move, the Cloudflare Pages setup, and the waiting list's Resend and D1 setup.
`RUNBOOK.md` is the recurring half: shipping a change, the weekly and monthly
checks, looking after the list, and what to do when mail stops going out.

`public/view.html` is a development harness, not a page: it frames the site at
1440, 900 and 390 side by side so responsive behavior can be checked in one
view. `window.setW`, `setFrameScroll` and `scrollAll` are available on it.

Note that Chrome suspends rendering in hidden tabs, so the hero slideshow, the
scroll reveals and the composing floor will all appear stuck if the tab is not
visible. That is the browser, not the page.
