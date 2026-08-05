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
- It is **not wired to any deploy**. `astro.config` is untouched, so rule 6 is
  not affected, and nothing here publishes.

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
| Norm | `prototypes/App Interface.dc.html`, the chat. Mug SVG, steam keyframes, `THINK` phrases and `CHATS` exchanges are the prototype's |

The hero video is a recording of the committed prototype, walked end to end.

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
- **The pricing block claims the agent is a Pro feature.** That copy came from
  the prototype's plan screen, which governs nothing, and SPEC 14.10's tier
  table does not put the agent behind Pro. The Norm section makes no tier
  claim, so the page currently contradicts itself. This is a known defect.
- The plan tiers, prices and trial length are the prototype's, not 14.10's.

## Running it

```
cd landing
npm install
npm run dev          # http://localhost:5201
```

`public/view.html` is a development harness, not a page: it frames the site at
1440, 900 and 390 side by side so responsive behavior can be checked in one
view. `window.setW`, `setFrameScroll` and `scrollAll` are available on it.

Note that Chrome suspends rendering in hidden tabs, so the hero video, the
scroll reveals and the chart draw will all appear stuck if the tab is not
visible. That is the browser, not the page.
