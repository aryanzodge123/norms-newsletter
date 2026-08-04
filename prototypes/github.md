repo: aryanzodge123/norms-newsletter
branch: main
path: site/

## Last sync
date: 2026-08-02T18:35:00Z

### Updated in this project
- Pulled the new August 2, 2026 edition (No. 056, 11 stories, 6:52 audio) into `site/content/editions/` and regenerated `norm-editions.js` — 14 editions, 178 stories, 166 grounded.
- Today's brief, Listen, Archive, Stories and Norm all pick the new edition up from the data module; the Strait of Hormuz story is now the headline of the day.
- Refreshed the hardcoded variants to No. 056: masthead front page (1b), digest (1c), sheet reader (1d), single feed (1e) and the 6:00 am push + lock screen (1f), plus the by-the-numbers tiles (118 items in, 8 sources).
- Regenerator now also carries `flat: true` for ungrounded stories and `quoteText`/`quoteAttr` from `article.quote` — both are contracts the reader relies on.

### Previous entry (2026-08-02T01:22Z)
- Imported all 13 committed editions (2026-07-20 → 2026-08-01) and generated `norm-editions.js` as the prototype's single data source.
- Added the "How Norm works" and "RSS and podcast feed" pages, the in-app Safari-style browser, and the motion pass (rising player, push reader).
- `norm-editions.js` is an ES module imported by the logic class (a helmet `<script src>` re-mounted per render and hung the page — do not put it back).

## Screen map
| Project screen | Built from |
|---|---|
| Today's brief (1a) | norm-editions.js ← site/content/editions/2026-08-02.json (latest), site/src/styles/tokens.css, site/src/styles/global.css, site/src/components/README.md |
| Story reader (1a, 1d) | `article` fields (background / what_happened / why_it_matters / quote) in the edition JSONs |
| Listen (1a) | `audio` block of the latest edition (duration_seconds) |
| Archive + Stories (1a) | All 14 editions in site/content/editions/ |
| Settings / More (1a) | site/src/components/README.md; feed URLs from astro.config (site + base) |
| Home layout variants (1b, 1c) | 2026-08-02.json, re-composed by hand |
| No-tab single feed (1e) | site/src/styles/global.css container + DS prevnextbar; 2026-08-02.json |
| Push + lock screen (1f) | 2026-08-02.json headline + audio duration; palette from tokens.css |
| App onboarding (App Onboarding.dc.html) | Project-original flow; section list mirrors the site's topic taxonomy |

## Sync history
### 2026-08-02T01:22:00Z
- Backfilled 13 editions, rebuilt the app on real data, added the in-app browser, More sub-pages and podcast deep links.

### 2026-07-25T17:52:10Z
- Recreated the newsletter's visual system (tokens, type roles, components) as a native iPhone app prototype.
- Built the July 25, 2026 edition (No. 048) from the committed `edition.json`.
- Added app-only affordances the static site lacks: 6:00 am push, background/lock-screen audio, docked mini-player, dark variant.
