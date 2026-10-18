# `scripts/` - operator tooling

Small, standalone command-line helpers for the person **operating** the project.
These are not part of the pipeline (`src/`) and are never imported by it. They
exist to make day-to-day running and debugging easy. See
[`../RUNBOOK.md`](../RUNBOOK.md) for how they fit into operations.

## `norm.py` - read-only status and table inspector

The one command a caretaker runs to answer "is it healthy?" and "what is in the
tables?" without writing any database code.

**It is strictly read-only.** It only ever *reads* (scans tables, reads files on
disk). It never writes, overwrites, deletes, or calls an AI model, so running it
can never change the pipeline or cost money. It reuses the table schemas already
defined in `src/` rather than defining anything new.

```bash
uv run python scripts/norm.py status               # health snapshot (this is the default)
uv run python scripts/norm.py runlog --days 3      # recent job runs, newest first
uv run python scripts/norm.py runlog --job collector
uv run python scripts/norm.py table silver --date 2026-07-20
uv run python scripts/norm.py cost --days 7        # estimated AI spend per day
```

| Subcommand | What it shows |
|------------|---------------|
| `status` | The latest committed edition, the most recent run of each job with its age, a warning if the collector has gone stale, and any non-success runs in the last 2 days. |
| `runlog` | Rows from `ops.run_log`, newest first. Filter with `--days` and `--job`. |
| `table`  | A row count and a peek at `bronze`, `silver`, `runlog`, or `editions` (optionally for one `--date`). |
| `cost`   | `ai_cost_estimate_usd` summed per day, with a rough monthly projection against the under-$25 budget. |

Reading the tables needs the same R2 credentials in `.env` that the pipeline
uses. If they are missing, the script prints a clear message and exits, rather
than showing a traceback.

> **Why is it not called `inspect.py`?** Because that would shadow Python's
> standard-library `inspect` module, which PyIceberg imports. A file named
> `inspect.py` on the path breaks the import. The name `norm.py` avoids that.

## `writer_eval.py` - compare writer models before switching

The measured comparison SPEC 6.5 and section 11 require before the writer stage
changes model. It reruns the real writer stage over past editions, once per
model, on exactly the inputs production used that day: the stories the editor
picked, their excerpts from gold, and the same prior mentions. Only the model
changes.

**Unlike `norm.py`, it calls the API and costs money**, about $0.50 for ten
days comparing Haiku 4.5 with Haiku 5.5. It never writes to the lake. Always
look at the dry run first.

```bash
uv run python scripts/writer_eval.py --days 10 --dry-run   # list the stories, no API calls
uv run python scripts/writer_eval.py --days 10             # run both default models
uv run python scripts/writer_eval.py --days 10 \
    --arm old=claude-haiku-4-5-20251001 \
    --arm new=claude-haiku-5-5:high:8192                    # label=model[:effort[:max_tokens]]
```

It writes `eval-out/writer/<timestamp>/report.md` (and `results.json` with
every article). The report has two parts:

- **A summary table** per model: articles written, retries, first-draft
  readability grade against the gate's 9, cost, and time.
- **Grounding candidates to review.** Every number or capitalised name in an
  article that never appears in what the writer was shown, with its sentence.
  These are candidates, not findings: a person ticks the ones that are real
  additions, which is the part a script cannot judge. The check is tested in
  `tests/test_writer_eval.py`.

Effort and output cap are applied to the request by the script, so a setting
can be evaluated before any production code changes.
