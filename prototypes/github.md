repo: aryanzodge123/norms-newsletter
branch: main
path: site/

## Last sync
date: 2026-08-25T22:40:00Z

### Updated in this project
- Pulled 23 new editions (2026-08-03 → 2026-08-25) into `site/content/editions/` and regenerated `norm-editions.js` — 36 editions, 482 stories, 444 grounded.
- Every screen opens on **No. 074 (Thursday, August 20, 2026)** — "US warns of AI attacks on Siemens industrial gear," 16 stories, 6:09 audio, 192 items in / 20 sources. `norm-editions.js` is generated with a `<= 2026-08-20` cutoff (32 editions), so Aug 21–24 sit in `site/content/editions/` unused; remove the cutoff to move forward again.
- Refreshed every hardcoded variant to No. 074: masthead front page (1b), digest (1c), sheet reader (1d), single feed (1e), 6:00 am push + lock screen (1f), the by-the-numbers tiles (145 items in, 12 sources), the onboarding wire ticker and "today at a glance" card, and Norm's opening chat.
- 2026-08-25 (No. 079) is an `edition_type: "fallback"` — a notice plus 10 ranked links, no sections, audio or key points. It is excluded from `norm-editions.js` so no screen renders empty; the prototype has no fallback state yet.

### Previous entry (2026-08-02T18:35Z)
- Pulled the August 2 edition (No. 056) and regenerated `norm-editions.js` — 14 editions, 178 stories, 166 grounded.
- Regenerator carries `flat: true` for ungrounded stories and `quoteText`/`quoteAttr` from `article.quote` — both are contracts the reader relies on.
- `norm-editions.js` is an ES module imported by the logic class (a helmet `<script src>` re-mounted per render and hung the page — do not put it back).

## Screen map
| Project screen | Built from |
|---|---|
| Today's brief (1a) | norm-editions.js ← site/content/editions/2026-08-24.json (latest full edition), site/src/styles/tokens.css, site/src/styles/global.css, site/src/components/README.md |
| Story reader (1a, 1d) | `article` fields (background / what_happened / why_it_matters / quote) in the edition JSONs |
| Listen (1a) | `audio` block of the latest edition (duration_seconds; null on 08-07, 08-13, 08-19) |
| Archive + Stories (1a) | All 36 full editions in site/content/editions/ |
| Settings / More (1a) | site/src/components/README.md; feed URLs from astro.config (site + base) |
| Home layout variants (1b, 1c) | 2026-08-24.json, re-composed by hand |
| No-tab single feed (1e) | site/src/styles/global.css container + DS prevnextbar; 2026-08-24.json |
| Push + lock screen (1f) | 2026-08-24.json headline + audio duration; palette from tokens.css |
| App onboarding (App Onboarding.dc.html) | Project-original flow. Its `NOTIFS`, `FEED`, wire ticker, glance card and per-topic `HOME` section stubs are hand-authored copies of edition content — refresh all of them from the latest full edition on every sync |
| App interface (App Interface.dc.html) | norm-editions.js; Norm chat seeded from the 08-24 headline story |
| Brand (Norms Newsletter Brand.dc.html) | Project-original; mark and banner lockups, not repo-derived |

## Sync history
### 2026-08-02T18:35:00Z
- Pulled No. 056, refreshed the hardcoded variants, added `flat`/quote fields to the regenerator.

### 2026-08-02T01:22:00Z
- Backfilled 13 editions, rebuilt the app on real data, added the in-app browser, More sub-pages and podcast deep links.

### 2026-07-25T17:52:10Z
- Recreated the newsletter's visual system (tokens, type roles, components) as a native iPhone app prototype.
- Built the July 25, 2026 edition (No. 048) from the committed `edition.json`.
- Added app-only affordances the static site lacks: 6:00 am push, background/lock-screen audio, docked mini-player, dark variant.
