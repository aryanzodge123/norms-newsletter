# `src/silver/` - dedup, clustering, and scoring (the "copy desk")

The silver stage takes the raw items sitting in `bronze.raw_items` and turns them
into **rated story clusters**: groups of items that are all about the same
real-world event, each with a newsworthiness score and a topic. Its output table
`silver.story_clusters` is what the editor reads the next morning.

In newsroom terms: bronze is the wire feed, silver is the copy desk that removes
duplicates, bundles the follow-ups together, and marks which stories matter.

## The pipeline in this folder

```
bronze.raw_items (one day)
   |
   v  dedup.py    drop duplicate item_ids and same-day duplicate URLs
   |
   v  cluster.py  embed each item locally, greedily group similar ones
   |
   v  score.py    ask a small AI to rate each NEW or CHANGED cluster (1-10)
   |
   v  table.py    overwrite today's partition of silver.story_clusters
```

`run_silver.py` is the entry point that orchestrates all four.

## The files

| File | What it does |
|------|--------------|
| `run_silver.py` | Entry point. Reads bronze, runs dedup/cluster/score, writes silver, logs the run. |
| `dedup.py` | Drops duplicate `item_id`s and same-day duplicate `canonical_url`s. Pure code. |
| `cluster.py` | Local text embeddings + greedy clustering. The only "AI-ish" part is free and local. |
| `score.py` | The one paid AI call in this stage: rate a cluster, with schema validation + retry. |
| `table.py` | The `silver.story_clusters` schema, plus per-partition read and overwrite. |

## Key ideas a junior engineer should understand

### Clustering costs nothing, so the whole day is rebuilt every run

Embeddings are computed **locally** with `sentence-transformers` (model
`BAAI/bge-small-en-v1.5`). No API, no per-run cost. That is what makes the
"rebuild the whole day's partition every run" strategy affordable: each silver
run re-reads the entire day's bronze, re-clusters it from scratch, and
**overwrites** today's silver partition. A missed or crashed run simply corrects
itself on the next one. This is why the stage is idempotent.

### Greedy clustering

`cluster.py` walks items in published-time order. Each item joins the most
similar existing cluster if their cosine similarity is at or above
`cluster_threshold` (0.82, in config); otherwise it starts a new cluster. Two
items with an identical URL always merge regardless of the score. The earliest
item in a cluster is its "seed" and defines the cluster's stable `cluster_id`
(`sha256(seed_item_id)`), which stays the same every time the day is
re-clustered.

### Scoring is the only paid AI call, and it is incremental

`score.py` calls a small, cheap model (Claude Haiku) that returns strict JSON:
`{score 1-10, topic, rationale (one sentence), confidence}`. Two things keep it
cheap:

1. **Prompt caching.** The scoring rubric is a long, identical prefix on every
   call, so after the first call in a 5-minute window the model reads it from
   cache at ~10% of the cost. The code even checks the rubric is long enough for
   caching to engage.
2. **Incremental re-scoring.** `run_silver.py` only scores clusters that are
   **new** or whose **member count changed** since the last run. Unchanged
   clusters carry their old score forward for free.

If a cluster's response fails validation twice, its score is stored as `null`,
and the editor ignores it. One bad cluster never fails the run.

### The table is the future evaluation dataset

Every stored row carries `model_version`, `prompt_version`, and `scored_at`
alongside the score and its rationale. That is on purpose: SPEC calls this table
the future eval dataset, and a score without a record of what produced it is not
evaluable. The weekly review uses this to tune the threshold and the rubric.
