# `src/adapters/` - the source adapters (the "reporters")

An **adapter** is a small class that knows how to fetch from **one** news source
and turn what it gets into the project's single standard row shape (a
`RawItem`). This is the only part of the pipeline that talks to the outside
world's news sources. There is no AI here at all.

Think of each adapter as one reporter who only covers one beat and always files
copy in the exact same format.

## The contract every adapter follows

Every adapter has a `name`, a `topic_hint`, and a `fetch(since)` method that
returns a list of `RawItem` objects. The shared machinery in
[`base.py`](base.py) does the important, dedup-critical work so no adapter has to
get it right on its own:

- **`build_item(...)`** assembles a `RawItem`, deriving the fields that must be
  consistent across every source.
- **`canonicalize(url)`** cleans a URL deterministically (lowercases the host,
  strips tracking parameters like `utm_*` and `fbclid`, drops the fragment,
  removes a trailing slash) and, only for known link-shortener hosts, follows
  redirects to the real URL.
- **`make_item_id(...)`** computes `item_id = sha256(canonical_url +
  published_at)[:32]`. This is how duplicates are detected across the whole
  system.

> **Important:** the URL-cleanup rules in `base.py` are **frozen per spec
> version**. Changing them changes every `item_id` and breaks deduplication
> against existing stored rows. They only change with a version bump and a
> documented migration. (The list of shortener hosts, by contrast, can change
> anytime, because a rare duplicate is acceptable but a broken hash is not.)

## The files

| File | Source | Type | Key needed? |
|------|--------|------|-------------|
| `base.py` | *(shared contract + URL/id/excerpt helpers, no source of its own)* | - | - |
| `hackernews.py` | Hacker News (Firebase API) | api | no |
| `arxiv.py` | arXiv cs.AI / cs.LG (Atom API) | api | no |
| `federal_register.py` | US Federal Register (JSON API) | json | no |
| `cisa.py` | CISA cybersecurity advisories (RSS) | rss | no |
| `arstechnica.py` | Ars Technica (RSS) + shared RSS date parsing | rss | no |
| `rss.py` | **The generic RSS adapter** used by most feeds | rss | no |
| `newsapi.py` | NewsAPI top headlines | api | **yes** (`NEWSAPI_KEY`) |
| `finnhub.py` | Finnhub market news | api | **yes** (`FINNHUB_KEY`) |
| `fred.py` | FRED economic releases | api | **yes** (`FRED_KEY`) |

## Two kinds of adapter

1. **Generic, config-driven.** `rss.py` (`RSSAdapter`) is one class that serves
   *every* plain RSS feed. The feed's URL lives in
   [`../../config/sources.yaml`](../../config/sources.yaml) as `feed_url`, not in
   the code, so **adding a normal RSS source is a config edit, not a new file**.
   Most of the sources in the registry use this one class.

2. **Bespoke.** Sources with their own quirks get their own file: Hacker News
   (Firebase API), arXiv (a query endpoint with a fixed category filter), the
   Federal Register (JSON), the keyed APIs (NewsAPI, Finnhub, FRED), and CISA (a
   thin subclass of `RSSAdapter` with its feed URL fixed in code).

## The rules adapters live by

- **One failing source never fails the run.** The collector wraps each adapter
  in a try/except: a source that errors is logged and skipped, and the run is
  marked `partial`, not `failed`.
- **One malformed item is skipped, never fatal.** Inside an adapter, a single
  bad entry (missing title, unparseable date) is dropped, and the rest of the
  feed still comes through.
- **Respect `max_items_per_run`.** Each source has a per-run cap in the registry.
- **Keyed sources ship disabled.** NewsAPI, Finnhub, and FRED are in the registry
  with `enabled: false` and raise a clear error at construction if their key is
  missing, so an unattended run stays clean until a key is provided.
- **Keys come only from `config.get_settings()`**, never from `os.environ`
  directly (see the project-wide rule that `config.py` is the only env reader).

## How an adapter is wired in

1. Add an entry to [`../../config/sources.yaml`](../../config/sources.yaml) with
   its `name`, dotted `adapter` path, `topic_hint`, `max_items_per_run`, and
   (for `RSSAdapter`) a `feed_url`.
2. `collector.py` reads the registry, imports the class by its dotted path, and
   calls `fetch(since)` on it.

The `since` window overlaps on purpose (the collector runs every 3 hours but
looks back further), so a missed cycle backfills itself and bronze dedups the
overlap.
