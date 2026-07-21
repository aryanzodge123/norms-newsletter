# `config/` - configuration

Two YAML files control how the pipeline behaves without touching code. They are
loaded and validated (with pydantic) by [`../src/config.py`](../src/config.py) at
startup, so a malformed file or a missing credential fails loudly and
immediately rather than halfway through a run.

Secrets are **not** here. Credentials live in a local `.env` file (or GitHub
Actions secrets in CI), and `src/config.py` is the only module that reads them.
No key is ever written into these files.

## The files

### `sources.yaml` - the adapter registry

The list of news sources. Each entry says which adapter class to use, what topic
to hint, how many items to pull per run, and whether it is enabled. For generic
RSS feeds it also gives the `feed_url`. Adding a normal RSS source is just a new
entry here (no code). Keyed sources (NewsAPI, Finnhub, FRED) are listed with
`enabled: false` until their API key is set.

### `pipeline.yaml` - the operational knobs

Everything tunable about the pipeline, grouped by stage:

| Section | Controls |
|---------|----------|
| `collector` | How far back each run looks (`since_window_hours`) |
| `enrich` | Article-text fetching: size/time limits, and hosts to skip |
| `silver` | The embedding model, `cluster_threshold` (0.82), the scoring model and retries |
| `editor` | The editor/writer models, concurrency, edition-type thresholds, grounding floor, readability passes |
| `audio` | The script model, the text-to-speech model and voices, and the word band |
| `archive` | Prior-mention lookback window and snapshot expiry |
| `canonical_url` | `shortener_hosts`: which link-shortener hosts are worth resolving |

## Frozen vs. tunable

A useful distinction when editing these:

- **Tunable freely:** model ids, thresholds, budgets, the source list, and
  `shortener_hosts`. Changing these is a normal config change.
- **Frozen per spec version:** the URL *cleanup* rules (in
  [`../src/adapters/base.py`](../src/adapters/base.py), not here) feed the dedup
  hash. `shortener_hosts` is safe to change because a rare duplicate is
  acceptable, but the cleanup rules themselves are not.

Also note: `cluster_threshold` is calibrated against the specific
`embedding_model`, so swapping the model means re-tuning the threshold, not just
editing one line.

Keys are added to `pipeline.yaml` by the milestone that needs them, never
speculatively.
