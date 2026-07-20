# MILESTONES.md

Build log. One entry per milestone from SPEC.md section 12: what was
built, which spec sections it satisfies, how it was verified, and what was
deferred.

---

## M1 Skeleton

Date: 2026-07-19
Spec: SPEC 12.1, 6.1, 6.2, 6.3, 6.10, section 8
Status: complete, gate green

### What was built

**Configuration (SPEC 6.10).** `src/config.py` loads `config/sources.yaml`
and `config/pipeline.yaml` plus `.env`, validates everything with pydantic
models that reject unknown keys, and is the only module in the codebase
that reads environment variables. R2 credentials are required;
later-milestone keys are optional so an M1 run does not demand an M6 key.

**Normalization primitives (SPEC 6.1).** `src/adapters/base.py` holds the
`RawItem` model, the `Adapter` protocol, `clean_url`, `canonicalize`,
`make_item_id`, and `build_item`. Adapters call `build_item` rather than
constructing rows directly, so the dedup-critical derivations happen in
one place. `make_item_id` pins the published_at string form to
`%Y-%m-%dT%H:%M:%SZ` in UTC, so an adapter's choice of tzinfo cannot
change an item_id.

**Adapters (SPEC 6.1).** `hackernews.py` (Firebase API, no key) and
`arstechnica.py` (RSS). Both cap at `max_items_per_run`, filter on
`since`, and skip malformed entries rather than failing the feed.

**Storage (SPEC 6.3, section 8).** `src/storage.py` owns the R2 Data
Catalog connection. `src/bronze.py` defines `bronze.raw_items`,
partitioned by `ingest_date`, with an append that deduplicates both within
the batch and against stored partitions. `src/runlog.py` defines
`ops.run_log` per the section 8 table, partitioned by `run_date`, with
`make_run_id` producing the SPEC 6.1 format.

**Collector (SPEC 6.2).** `src/collector.py` resolves adapters from the
registry, runs each inside its own try/except, writes bronze, and records
one run_log row. A failing adapter makes the run `partial`, never
`failed`. The run_log write sits in a `finally` block so a failed bronze
write still leaves a record.

### How it was verified

**Tests: 76 passing, all offline.** Hacker News runs through
`httpx.MockTransport`, Ars Technica parses fixture text, and Iceberg
writes go to a local sqlite catalog, so the suite needs no credentials.

```bash
uv run pytest -q
```

Coverage by layer: canonical_url cleanup rules including idempotency and
the shortener fallback path; item_id determinism across timezone
representations; adapter normalization, `since` filtering, item caps, and
malformed-entry handling; config validation failures; bronze idempotency
and cross-partition dedup; run_log row shape and status validation;
collector adapter isolation.

**Live run against R2**, three commands in sequence:

```bash
uv run python -m src.collector --dry-run   # fetches, prints, writes nothing
uv run python -m src.collector             # wrote 19 rows, skipped 0
uv run python -m src.collector             # wrote 0 rows, skipped 19
```

The third command is the idempotency proof required by SPEC 6.2.

**Stored state confirmed by reading it back** (DuckDB over a PyIceberg
scan):

```bash
uv run python -c "
import duckdb
from src.storage import get_catalog
from src import bronze, runlog
items = bronze.ensure_table(get_catalog()).scan().to_arrow()
runs = runlog.ensure_table(get_catalog()).scan().to_arrow()
con = duckdb.connect()
print(con.execute('SELECT source, count(*), count(DISTINCT item_id) FROM items GROUP BY source').fetchall())
print(con.execute('SELECT run_id, job, status, items_in, items_out FROM runs ORDER BY started_at').fetchall())
"
```

Result: 19 bronze rows (18 hackernews, 1 arstechnica), every item_id and
canonical_url distinct. Two run_log rows, the second showing
`items_in=19, items_out=0`, which is idempotency visible in the
observability table rather than only in a log line.

**Gate:** `uv run python .claude/skills/milestone-verify/verify.py` passes
with tests green and fixtures and urls correctly skipped until M3 and M4.

### Decisions and notes

- `src/` is a Python package, so registry paths written in the SPEC 6.1
  form (`adapters.hackernews.HackerNewsAdapter`) resolve under it. The
  yaml stays verbatim per the spec.
- Module placements not named in SPEC section 5: `adapters/base.py`,
  `storage.py`, `bronze.py`.
- Dependencies added: `pyyaml`, `pyiceberg[sql-sqlite]` (local catalog for
  tests), and `pytest` in a dev group.
- Two bugs the tests caught during the build. The redirect resolver was
  being tested with a handler that failed on the second hop, and the HN
  fixture encoded escaped entities where the real API sends actual tags,
  which masked the strip-then-unescape ordering in `strip_html`.
- Observed: the HN adapter walks the full ranked topstories list
  sequentially, roughly 500 requests and about 30 seconds per run, because
  the list is ranked by score rather than time and cannot be short
  circuited on `since`. Correct and free, but a candidate for
  parallelization during the M6 tuning window.

### Deferred

- systemd timer and the disabled Actions backup launcher (SPEC 6.2
  runtime): not in the M1 scope line, lands with M5 automation.
- healthchecks.io ping for collector cadence: M5.
- The remaining v1 sources in SPEC 6.1: M6.

### Open question raised for the spec

`make_item_id` needs a fixed string form for published_at or the hash is
not reproducible. SPEC 6.1 gives the formula but not that encoding. It is
pinned in code and covered by tests. Worth writing into SPEC 6.1 as an
explicit clause, since it belongs to the frozen rules.
