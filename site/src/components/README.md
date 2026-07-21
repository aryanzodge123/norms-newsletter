# `site/src/components/` - the page components

Each file here is one reusable piece of the page, and each maps directly to a
component named in **[DESIGN.md](../../../DESIGN.md) section 4**. DESIGN.md is the
source of truth for how each one looks and behaves; the file header comments cite
it. There is no logic here beyond templating and styling (no AI, rule zero).

A guiding design principle worth knowing: **the frame never changes.** The
masthead, the double rules, and the footer are identical on every page and every
edition type. Only the middle varies. And **type encodes origin**: serif
(Newsreader) is the day's headline and quoted human voices, sans (IBM Plex Sans)
is editorial writing, mono (IBM Plex Mono) is machine output (dates, scores,
counts).

## The components

### The frame (on every page)

| Component | What it renders |
|-----------|-----------------|
| `Masthead.astro` | Top bar: date / wordmark / edition number. On non-edition pages, a back link + page name. |
| `Footer.astro` | Bottom rule + "Compiled by Norm at 6:00 am ET". |
| `PageShell.astro` | The frame for non-edition pages (archive, about, methodology, subscribe). |

### The edition body

| Component | What it renders |
|-----------|-----------------|
| `EditionView.astro` | **The template switch.** Composes an edition into its normal/quiet/fallback layout. |
| `AudioRow.astro` | The audio player row. Omitted entirely when `audio` is null. |
| `GlanceBlock.astro` | The "Today at a glance" numbered points (`key_points`). |
| `SectionLabel.astro` | A section heading ("Artificial intelligence", spelled out in full). |
| `StoryCard.astro` | One story: a native `<details>` card that expands into the article. Deep-linkable by slug. |
| `PullQuote.astro` | An optional person-speech quote inside an expanded story. |
| `Sidebar.astro` | Desktop "By the numbers" stats box + nav links. |
| `StatTiles.astro` | The mobile replacement for the sidebar (a small grid of tiles). |
| `BrieflyStrip.astro` | The "Briefly" list of stories that did not get a full card. |
| `PrevNextBar.astro` | Previous-edition link and "Browse the archive". |

### Fallback-only

| Component | What it renders |
|-----------|-----------------|
| `NoticeBanner.astro` | The amber "Abbreviated edition" notice. **The only place the amber tint appears.** |
| `RankedList.astro` | The fallback edition's ranked top-10 list with links. |

### Archive

| Component | What it renders |
|-----------|-----------------|
| `ArchiveRow.astro` | One row on the archive page: date, headline, story count, audio length. |

## How they connect to the data

Components receive typed props derived from `edition.json`. The type comes from
[`../content.config.ts`](../content.config.ts), which validates every edition
against the schema at build time, so a malformed edition fails the build instead
of rendering broken HTML. `StoryCard` is the interesting one: when a story's
`article` is `null` (the writer stage could not ground it), the card renders as a
plain, non-expandable div with a "Read at:" link out, instead of a `<details>`
element. That is the front-end half of the pipeline's "contain failures at the
story level" rule.

## Styling

All colors, fonts, and spacing come from CSS custom properties (design tokens) in
[`../styles/tokens.css`](../styles/tokens.css), which is DESIGN.md section 3 made
concrete. Components use those tokens rather than raw hex values, so the whole
look changes from one file. The site is light-only in v1 (no dark mode).
