# `tests/` - the test suite

The tests cover the **deterministic layers** of the pipeline: the parts where
there is one correct answer that code can check. The AI stages themselves are
not tested (they are judgment calls), but their schema validators, retry paths,
and fallback behavior are.

Everything here runs **fully offline**, with no credentials and no network:

- Network-facing adapters are driven through `httpx.MockTransport` (fake HTTP).
- Iceberg writes go to a **local SQLite catalog** on a temp path, standing in
  for Cloudflare R2.

See [`conftest.py`](conftest.py) for the shared fixtures (`local_catalog`, the
`make_item` helper, and the Hacker News / Ars Technica sample feeds).

## What is covered

| Area | Test files |
|------|-----------|
| Adapters + URL canonicalization + item ids | `test_adapters.py`, `test_adapters_m6.py`, `test_canonical.py`, `test_item_id.py` |
| Collector + enrichment | `test_collector.py`, `test_enrich.py` |
| Bronze table | `test_bronze.py` |
| Dedup + clustering + scoring | `test_dedup.py`, `test_cluster.py`, `test_score.py` |
| Silver run + table | `test_run_silver.py`, `test_silver_table.py` |
| Edition context / planning / schema | `test_edition_context.py`, `test_edition_plan.py`, `test_edition_schema.py` |
| Writer stage + prior mentions | `test_writer_stage.py`, `test_prior_mentions.py` |
| Full edition run | `test_run_edition.py` |
| Readability + simplify | `test_readability.py`, `test_simplify.py` |
| Audio (script, tts, run) | `test_audio_script.py`, `test_tts.py`, `test_run_audio.py` |
| Archive | `test_archive.py` |
| Run log + health + DST scheduling | `test_runlog.py`, `test_health.py`, `test_schedule.py` |
| Config loading | `test_config.py` |

## Running them

```bash
uv run pytest -q            # the whole suite
uv run pytest tests/test_cluster.py -q   # one file
```

The tests are also run as the first check of the milestone-verify gate
(`.claude/skills/milestone-verify/verify.py`), which is the end-of-milestone
gate every milestone must pass before it is logged.

## Why the AI is not tested here

Per rule zero, the AI only makes judgments and always returns schema-validated
JSON. Testing "did the model pick good stories" is a review task for a human, not
a pytest assertion. What *is* testable, and *is* tested, is the machinery around
the AI: does an invalid response trigger the retry, does a second failure fall
back correctly, does a bad story get contained to a null article without breaking
the edition. Those are the tests that protect the "never break, only degrade"
promise.
