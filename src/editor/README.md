# `src/editor/` - building the daily edition (the "newsroom")

This is the most involved subsystem. It takes the day's rated clusters from
`silver.story_clusters` and produces one validated `edition.json`: the headline,
the "Today at a glance" points, the sections of stories, each story's article,
and the stats. That file is the contract between "what the AI decided" and "what
the site renders."

Two AI stages run here (the **editor** and the **writers**), plus a
**readability gate**. Everything around them is deterministic code, and the
schema is the referee.

## The flow

```
silver.story_clusters + bronze (one day)
   |
   v  context.py   join clusters back to their raw items (URLs, excerpts)
   |
   v  plan.py      decide IN CODE: edition type, sections, edition number, slugs, stats
   |
   v  run_editor.py   AI stage 1 (Sonnet): pick + order stories, write headline, glance, summaries
   |
   v  run_writers.py  AI stage 2 (Haiku, parallel): write each story's 3-paragraph article
   |
   v  assemble.py  stitch curation + articles + pipeline facts into edition.json
   |
   v  schema.py    validate the whole thing (the authority on a valid edition)
   |
   v  readability.py + simplify.py   measure reading grade, rewrite anything too hard
   |
   v  site/content/editions/<date>.json
```

`run_edition.py` is the entry point that runs all of this and logs the run.

## The files

| File | Role | AI? |
|------|------|-----|
| `run_edition.py` | Entry point. Orchestrates everything, contains all failures, writes the file. | - |
| `context.py` | Joins each cluster to its raw items so stages see real URLs and article text. | - |
| `plan.py` | Structural decisions made **before** any AI call: edition type, section budget, slugs, edition number, stats. | - |
| `run_editor.py` | **Stage 1**: the editor agent. One larger call that curates the edition core. | yes |
| `run_writers.py` | **Stage 2**: the writer stage. One small parallel call per story for the article. | yes |
| `readability.py` | The reading-grade gate (Flesch-Kincaid). Pure math, no dependency, pinned by tests. | - |
| `simplify.py` | Rewrites editor-owned text (summaries, glance, headline) that reads too hard. | yes |
| `assemble.py` | Deterministic seam: joins AI output to pipeline facts, builds normal/quiet/fallback editions. | - |
| `schema.py` | The canonical `edition.json` schema. Written before any prompt. The referee. | - |
| `llm.py` | The shared "call, validate, retry once, or raise AIFailure" helper both stages use. | - |

## Concepts worth understanding

### The schema is written first and owns the truth

[`schema.py`](schema.py) is the canonical definition of a valid edition (it
matches SPEC 6.5, which is canonical for both SPEC and DESIGN). The AI stages are
constrained to schemas *derived from* these pydantic models, and every reply is
validated against them. Constraints that SPEC states only in prose (min/max
stories per section, key-point counts, "a quote must link to one of the story's
own sources," "no em dashes") live here as validators. If it is not enforced
here, it is not enforced.

### Code decides structure; the AI only decides judgment (rule zero)

`plan.py` makes every structural decision in plain code, before spending a cent
on AI:

- **Edition type** (`normal` / `quiet` / `fallback`) from how many usable
  clusters exist, using thresholds in config.
- **Which sections are available** (a section needs at least 2 stories; a
  one-story topic is "held" and spills to the "briefly" list).
- **Edition number, slugs, and stats**, all derived from facts the pipeline
  already owns.

The editor is then *told* which mode and which sections to work within. It is
never asked for a fact the code already knows.

### Two AI stages, failures contained at the story level

- **Editor (stage 1)** is one call. If it fails validation twice, the whole
  edition falls back to a ranked top-10 list (`fallback` type). That is the only
  edition-sized failure.
- **Writers (stage 2)** is one small call per story, run in parallel. A story
  fails "small": if its cluster has too little source text to ground an article
  (`min_grounding_chars`), no call is made and it publishes as a plain card; if
  its article fails validation twice, same result. Either way the *rest* of the
  edition is fine. This is why the article field is nullable.

### The readability gate

[`readability.py`](readability.py) implements Flesch-Kincaid grade level from
scratch (deliberately, so it is stable and pinned by tests). The edition average
must be grade 9 or below. If it is over, `run_edition.py` runs a revision loop
(up to `readability_max_passes`): [`simplify.py`](simplify.py) rewrites the
editor-owned lines that read hardest (summaries and glance points often grade
worst), and the writer stage is re-called for the stories that are themselves too
hard, with their hardest sentences listed. Quotes are never rewritten (that would
put words in a real person's mouth). If the edition is still too hard after the
budget is spent, it publishes anyway and sets a flag in the run log for the
weekly review. Availability beats perfection.

### Prior coverage

`context.retrieve_prior_mentions` lets a writer mention that a story was covered
before. Because `cluster_id` is not stable across days, the match is semantic:
the story is embedded and compared against recently *published* clusters in the
`gold` tables over a lookback window. Without a catalog it returns empty, which
is exactly what the offline tests rely on.
