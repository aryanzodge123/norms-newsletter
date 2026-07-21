# `site/` - the Astro static website

This is the front end: the static website and the podcast/RSS feed. It takes the
`edition.json` files the pipeline produces and turns them into HTML pages, a
feed, and per-edition share images. It is built with [Astro](https://astro.build)
and ships **almost no client JavaScript**.

The backend pipeline that *produces* the editions lives in
[`../src/`](../src/). This folder only *renders* them. There is **no AI here at
all**: the site is pure deterministic templating (rule zero).

The visual system, the components, and the writing voice are all defined in
[`../DESIGN.md`](../DESIGN.md). Every component file here maps to a component
named in DESIGN.md section 4.

## The single most important rule

**The site's absolute URL and base path are defined in exactly one place:
[`astro.config.mjs`](astro.config.mjs)** (`site` and `base`). Every absolute URL
on the site (canonical links, Open Graph tags, feed links, the audio enclosure's
own-site parts) derives from those two values through the helpers in
[`src/lib/urls.ts`](src/lib/urls.ts). **A hardcoded self URL anywhere is a bug**,
and the milestone-verify gate greps for exactly that. The pre-launch migration
(SPEC section 13) changes those two values and nothing else.

## How a page gets built

```
content/editions/<date>.json   (committed by the pipeline, the publication record)
        |
        v  content.config.ts   validates each file against the edition schema at build time
        |
        v  src/lib/editions.ts  loads editions, sorts newest-first, computes neighbours/topics
        |
        v  src/pages/*          routes: /, /YYYY/MM/DD/, /archive/, /about/, etc.
        |
        v  src/components/*     one component per DESIGN.md piece (Masthead, StoryCard, ...)
        |
        v  dist/                static HTML + feed.xml + OG images -> GitHub Pages
```

## Folder layout

| Path | What it is |
|------|-----------|
| `astro.config.mjs` | The one place `site` + `base` are defined (see the rule above) |
| `content/editions/` | One committed `edition.json` per day. **This is the publication record.** |
| `content.config.ts` | The build-time schema for editions (the front-end mirror of `src/editor/schema.py`) |
| `fixtures/` | `normal.json`, `quiet.json`, `fallback.json`: sample editions so the site develops with no live pipeline |
| `src/pages/` | The routes (see the table below) |
| `src/components/` | One `.astro` file per DESIGN.md component. See [`src/components/README.md`](src/components/README.md) |
| `src/layouts/BaseLayout.astro` | The `<html>`/`<head>` shell, meta tags, and the site's two tiny scripts |
| `src/lib/` | Helpers: `urls.ts` (all URL building), `editions.ts` (loading/formatting), `og.ts` (share images) |
| `src/styles/` | `tokens.css` (the design tokens from DESIGN.md section 3) and `global.css` |
| `dist/` | The built output (generated; deployed to GitHub Pages) |

## The routes

| Route | Page | Content |
|-------|------|---------|
| `/` | `index.astro` | The latest edition |
| `/YYYY/MM/DD/` | `[year]/[month]/[day].astro` | Permalink for each edition, identical layout |
| `/archive/` | `archive/index.astro` | Past editions, month-grouped, with topic filters |
| `/archive/{topic}/` | `archive/[topic].astro` | The archive filtered to one topic (prebuilt per topic) |
| `/about/` | `about.astro` | What this is, who Norm is, disclaimers, contact |
| `/methodology/` | `methodology.astro` | "How this brief is made": the pipeline and editorial policy |
| `/subscribe/` | `subscribe.astro` | RSS and podcast feed URLs and how to use them |
| `/feed.xml` | `feed.xml.ts` | RSS 2.0 + iTunes podcast feed, with audio enclosures |
| `/og/YYYY-MM-DD.png` | `og/[date].png.ts` | A per-edition Open Graph share image, rendered at build |

## The three edition types

The renderer switches on `edition_type` (from `edition.json`). All three exist as
fixtures so they can be developed and reviewed without running the pipeline:

- **normal** - the usual full brief: headline, audio, glance, sections of story
  cards, sidebar, briefly, prev/next.
- **quiet** - a slow day: same frame, fewer stories, a 3-point glance, and the
  sidebar shows "Sections held."
- **fallback** - something went wrong: just a notice in Norm's voice and a ranked
  top-10 list with links. No glance, no audio, no sidebar.

## The two scripts (the only client JavaScript)

Per DESIGN.md, the site works fully with JavaScript disabled. The only two
scripts are:

1. **Hash-target auto-open** (in `BaseLayout.astro`): opens the story card whose
   `id` matches the URL hash so `/#slug` deep-links, and handles the "Collapse"
   control. Story cards use native `<details>`/`<summary>`, so they still expand
   without JS.
2. **The native `<audio>` controls** (in `AudioRow.astro`).

## Developing locally

The site develops entirely against the fixtures. No credentials, no pipeline:

```bash
npm install
npm run dev        # local dev server
npm run build      # build to dist/ (also needed before the URL half of milestone-verify)
npm run preview    # preview the built site
```
