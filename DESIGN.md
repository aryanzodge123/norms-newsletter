# DESIGN.md - Norm's Newsletter

Status: v1.0 (locked for build)
Companion document: SPEC.md v1.2 (pipeline, schemas, workflows)
Note: all absolute URLs on the site derive from astro.config per SPEC 6.6;
no component hardcodes a URL.
Audience: written so a junior engineer can implement the Astro site directly
from this document.

Rule of ownership: SPEC.md owns data, schemas, and pipeline behavior.
DESIGN.md owns everything the reader sees and how it is written. Where the
two overlap (edition.json fields, edition types, the readability gate), the
schema definition in SPEC.md section 6.5 is canonical and this document
references it.

---

## 1. Brand

- Product name: **Norm's Newsletter**
- Norm is the AI editor persona. Norm collects, rates, and writes the brief.
  Machine-generated text on the site speaks as Norm ("Compiled by Norm at
  6:00 am ET"). System UI text never says "I".
- Tagline direction (About page, feeds): "A daily brief on technology, AI,
  business, finance, politics, and the world. Written in plain English.
  Compiled automatically every morning."
- Direction name: **Ledger**. Quiet, banker's-grade editorial. The design
  shows its own machinery: scores, source counts, and run stats are visible,
  designed elements.

## 2. Design principles

1. **The frame never changes.** Masthead, double rules, and footer are
   identical on every page and every edition type. Only the middle varies.
2. **Type encodes origin.** Serif = the day's single headline and quoted
   human voices. Sans = editorial writing. Mono = machine output (dates,
   scores, counts, stats). Never mix these roles.
3. **Depth everywhere, demanded nowhere.** The front page reads in 60
   seconds. Every story expands to a full article, but nothing requires it.
4. **Honesty over fullness.** Quiet days get shorter. Failures get a plain
   notice. The site never pads and never breaks.
5. **One accent.** Oxide green is the only interactive/label color. The
   amber notice tint appears only in the fallback edition banner.

## 3. Tokens

Implement as CSS custom properties in `site/src/styles/tokens.css`.

### 3.1 Color

| Token             | Hex       | Use                                          |
|-------------------|-----------|----------------------------------------------|
| --paper           | #F6F4EE   | Page background                              |
| --paper-raised    | #FBFAF6   | Boxed surfaces (audio row, glance, sidebar)  |
| --ink             | #23231F   | Primary text, masthead, heavy rules          |
| --ink-soft        | #44433C   | Body/summary text                            |
| --ink-2           | #2E2D27   | Glance text, quote text                      |
| --muted           | #6B6A62   | Mono metadata, captions                      |
| --oxide           | #3F6A50   | Accent: labels, links, markers, play icon    |
| --rule            | #DDD9CC   | Hairlines, box borders                       |
| --rule-faint      | #E8E5DA   | Intra-section story dividers                 |
| --notice-border   | #C9A24B   | Fallback banner border only                  |
| --notice-bg       | #FAF3E3   | Fallback banner background only              |
| --notice-title    | #7A5E1E   | Fallback banner label only                   |
| --notice-text     | #5C4A1E   | Fallback banner body only                    |

The site is light-only in v1. No dark mode.

### 3.2 Typography

Families (self-host via Fontsource npm packages; do not hotlink Google
Fonts at runtime):

- Display + quotes: **Newsreader** (400, 500, 400 italic)
- Body/UI: **IBM Plex Sans** (400, 500)
- Machine/meta: **IBM Plex Mono** (400, 500)

Scale (desktop / mobile):

| Role                    | Family, weight        | Size            |
|-------------------------|-----------------------|-----------------|
| Headline of the day     | Newsreader 500        | 31px / 23px, lh 1.25, ls -0.01em |
| Archive page title      | Newsreader 500        | 26px            |
| Pull quote              | Newsreader 400 italic | 15.5px, lh 1.55 |
| Story title             | Plex Sans 500         | 16-17px / 15.5px, lh 1.4 |
| Body, summaries         | Plex Sans 400         | 14px / 13.5px, lh 1.6-1.65 |
| Wordmark                | Plex Sans 500, caps   | 15px / 14px, ls 0.18em |
| Section label           | Plex Sans 500, caps   | 12px / 11.5px, ls 0.14em, --oxide |
| Article section label   | Plex Sans 500, caps   | 11.5px, ls 0.12em, --oxide |
| Mono metadata           | Plex Mono 400         | 12px / 11.5px   |
| Glance numerals         | Plex Sans 500         | 14px, --oxide   |

Weights: 400 and 500 only. Nothing bolder anywhere.

### 3.3 Rules and spacing

- Masthead rule: 2px solid --ink on top, 1px solid --ink below, 3px gap
  between (one div, border-top + border-bottom, height 3px).
- Footer rule: 2px solid --ink.
- Section label underline: 1px --rule. Story dividers: 1px --rule-faint.
- Boxed components: 1px --rule border, --paper-raised fill, no radius on
  the site itself (the ledger is square). Glance block adds border-top
  2px --oxide. Expanded story adds border-left 2px --oxide.
- Page container: max-width 720px centered, 40px side padding desktop,
  20px mobile. Vertical rhythm: 28-32px between major blocks, 16-18px
  inside them.

### 3.4 Breakpoint

One breakpoint at 720px. Below it: mobile layout (section 6).

## 4. Components

Names here match Astro component files in `site/src/components/`.

### Masthead.astro
Three columns on one baseline: date (mono, --muted), wordmark (caps,
centered), edition number "No. NNN" (mono, --muted). Edition number comes
from edition.json `edition_number` (SPEC 6.5). Mobile: wordmark centered
on its own line, "date . No. NNN" mono line beneath, both centered. The
double rule sits directly below in all cases. On non-edition pages the
left slot becomes a "Today's brief" back link and the right slot names the
page (e.g. "Archive").

### AudioRow.astro
Bordered row: play icon (--oxide), "Listen to today's brief" (sans 500),
duration (mono, --muted), right-aligned "Also on RSS" link (mono,
--oxide). Renders a native `<audio>` element revealed on play tap.
Duration comes from edition.json `audio.duration_seconds`. If `audio` is
null, the row is omitted entirely (no placeholder).

### GlanceBlock.astro
The "Today at a glance" box. Label left, "NN-second read" (mono) right;
read time = 12 seconds per point, rounded to a friendly value. Renders
edition.json `key_points` in order: two-digit numeral (--oxide, sans 500),
point text, inline topic tag (mono 11.5px --muted). 4-6 points on a
normal day, 3 on a quiet day. The glance replaces any intro paragraph;
never render both. Glance points never link.

### SectionLabel.astro
Caps label in --oxide over a 1px --rule underline. Section names render
in full ("Artificial intelligence", not "AI").

### StoryCard.astro
A styled `<details>` element. `<summary>` = the collapsed card: story
title, one-line summary (from `summary`), then a meta row with
"score N . M sources" (mono, --muted) left and "Read the full story" +
chevron (--oxide, sans 500 13px) right. Suppress the default disclosure
marker. Each story gets `id={slug}` so `/#slug` deep-links and a small
script can auto-open a story targeted by the URL hash.

Expanded content (inside `<details>`, from the `article` block):
- Wrapper gains border-left 2px --oxide with 20px left padding.
- Three labeled sections in order: Background, What happened, Why it
  matters. Article section label style, one paragraph each.
- Optional PullQuote between What happened and Why it matters.
- SourcesLine at the bottom: "Sources:" (mono --muted) then linked source
  names (--oxide) separated by middots, with "Collapse" + up chevron
  right-aligned.
- If `article` is null for a story (writer-stage failure, SPEC 6.5), the
  card renders as a plain div with no chevron and no expand affordance.

### PullQuote.astro
border-left 2px --rule, 16px padding-left. Quote text in Newsreader 400
italic, --ink-2. Attribution beneath in mono 11.5px --muted. Only renders
person-speech quotes supplied by the pipeline (policy in SPEC 6.5).

### Sidebar.astro (desktop only)
Grid column 172px. "By the numbers" box: caps label (--ink), then mono
label/value rows from `stats` (Items in, Clusters, Stories run, Sources).
Quiet editions swap the last row for "Sections held" and add a plain
explanatory sentence (12px --muted). Below the rows, a 1px --rule divider
and the "How this brief is made" link (--oxide). Under the box: stacked
links Archive, About, RSS and podcast (sans 13px --oxide, line-height 2).

### BrieflyStrip.astro
Section label ("Briefly", or "Briefly, from the quiet sections" when
`edition_type` is quiet), then mono 12.5px lines at line-height 2.1: title
(linked to source, --ink-soft) middot topic tag (--muted). Renders
edition.json `briefly`.

### PrevNextBar.astro
Bordered row: left "arrow-left  {prev date}: {prev headline}" and right
"Browse the archive arrow-right", both --oxide sans 13px. Built from the
committed editions on disk at build time. Omitted on edition No. 001's
left side.

### Footer.astro
2px --ink top rule, then mono 11.5px --muted, space-between: "Compiled by
Norm at 6:00 am ET" and "Every story links to its original sources".
Mobile: centered, first phrase only.

### NoticeBanner.astro
Fallback editions only. --notice-* tokens. Caps label "Abbreviated
edition", body in Norm's voice explaining the shortfall and that full
service resumes tomorrow. Never used for any other purpose.

### RankedList.astro
Fallback edition body: rows of two-digit rank (mono --oxide 500), story
title (sans 500, linked), "score N . source" (mono --muted), separated by
--rule-faint hairlines.

### ArchiveRow.astro
Baseline-aligned row: date "Jul 19" (mono --muted, min-width 56px),
headline (sans 500 14.5px, linked to the permalink), story count (mono
11.5px --muted), audio length with play glyph (mono --oxide). Grouped
under month SectionLabels.

### StatTiles.astro (mobile only)
2x2 (or 1x2) grid of small bordered tiles replacing Sidebar: mono label
over mono 15px value. Show Items in and Stories run at minimum.

## 5. Templates (edition types)

The renderer switches on edition.json `edition_type` (SPEC 6.5):

| edition_type | Template composition                                        |
|--------------|-------------------------------------------------------------|
| normal       | Masthead, headline, AudioRow, GlanceBlock, sections of StoryCards + Sidebar, BrieflyStrip, PrevNextBar, Footer |
| quiet        | Same as normal, fewer stories, 3-point glance labeled "30-second read", sidebar shows Sections held + sentence, BrieflyStrip carries the quiet sections. One glance point may be Norm speaking about the slow day, topic-tagged `norm` |
| fallback     | Masthead, NoticeBanner, RankedList (top 10), Footer. No glance, no audio, no sidebar |

All three exist as fixtures in `site/fixtures/` (normal.json, quiet.json,
fallback.json) so templates can be developed and visually reviewed without
running the pipeline.

## 6. Responsive behavior (below 720px)

- Single column. Sidebar is removed; StatTiles render after the last
  section; the sidebar links become a horizontal nav row above the footer
  (Prev date, Archive, About, RSS).
- Masthead stacks and centers (see Masthead.astro).
- Headline 23px. Body 13.5px. Meta 11.5px. Nothing below 11px.
- Boxes keep full-bleed-within-padding width. Tap targets minimum 44px
  tall for summary rows and nav links.

## 7. Pages

| Route                | Content |
|----------------------|---------|
| `/`                  | Latest edition (template per edition_type) |
| `/YYYY/MM/DD/`       | Permalink for each edition, identical layout |
| `/archive/`          | Past editions: month-grouped ArchiveRows, year tabs, topic filter links, "N editions since launch" footer count |
| `/archive/{topic}/`  | Same list filtered to editions whose stories include the topic (static, prebuilt per topic) |
| `/about/`            | What this is; who Norm is; who is behind Norm; what it is not (disclaimer: personal project, unaffiliated, not investment/legal/professional advice); contact |
| `/methodology/`      | "How this brief is made": three-sentence idea, pipeline diagram (static SVG), published editorial policy (rubric anchors, section budget, dead-section rule, paraphrase + link policy, quote policy, readability gate), running totals from gold, stack paragraph, builder signature |
| `/subscribe/`        | RSS feed URL, podcast feed URL and how to add it to podcast apps, two-line RSS explainer |
| `/feed.xml`          | RSS with edition headline, glance points, link, and podcast enclosure (iTunes namespace: title, author "Norm", description, 3000x3000 artwork, category News, per-episode enclosure URL/length/type from R2) |

Every page uses semantic HTML (header, main, section, article, footer),
one h1 per page, and works fully with JavaScript disabled. The only JS on
the site: hash-target auto-open for StoryCard and the audio element's
native controls.

## 8. Voice standard (canonical)

Applies to every word the pipeline generates: glance, summaries, articles,
briefly lines, audio script, notice banner. SPEC.md prompts implement it;
the readability gate (SPEC 6.5, run in the 6.8 workflow) enforces it.

1. Write for a smart friend outside the industry. Target roughly 8th-grade
   reading level (Flesch-Kincaid). Edition average must be grade 9 or
   below to publish.
2. No unexplained acronyms or terms. First use gets a plain definition in
   the same sentence.
3. Short sentences, one idea each, average under 20 words.
4. Numbers get honest context or get cut.
5. Every story answers, in order: what happened, then why a normal person
   should care. "Why it matters" is written about the reader's life.
6. At most one analogy per story, placed early.
7. Neutral and calm. No hype words, no fear words, no political
   editorializing. Norm reports what sources reported.
8. Never use em dashes. Periods, commas, or restructure.
9. Quotes: only a person speaking, at most one per story, short, always
   attributed and linked (full policy in SPEC 6.5).
10. Audio script: same rules; hosts define terms conversationally to each
    other.

## 9. Accessibility and performance floor

- Contrast: all text/background pairs above meet WCAG AA at their sizes
  (verified for --muted on --paper at 12px mono; do not lighten further).
- Keyboard: StoryCard uses native details/summary; visible focus outlines
  in --oxide; skip-to-content link.
- Images: the only images are the pipeline diagram (inline SVG with title/
  desc) and feed artwork. No hero images, no thumbnails in v1.
- Fonts: self-hosted, `font-display: swap`, subset latin. Total font
  payload under 300KB.
- Budget: Lighthouse 95+ on performance and accessibility for `/`. No
  client framework; Astro ships zero JS by default and that stays true
  except the two scripts named in section 7.

## 10. Assets to produce before launch

- Podcast/feed artwork, 3000x3000 PNG, ledger style (wordmark on paper
  with double rule).
- Favicon set (an "N." mark in Newsreader on --paper works).
- Open Graph image template: paper background, wordmark, date, headline
  (generated at build per edition with satori or a static fallback in v1).
- The methodology page's pipeline SVG.
