"""Writer model eval: the measured comparison SPEC 6.5 and section 11 ask for.

Runs the real writer stage (src/editor/run_writers.write_one) over past
editions, once per model, on exactly the inputs production gave it: the
stories the editor picked that day, their excerpts from gold, and the same
prior mentions. Only the model changes. It writes a report a person reads,
not a verdict: the decision belongs to Milind.

Two things are measured:

- Readability: the grade of each first draft, against the gate's 9.
- Grounding: numbers and capitalised names in the article that do not appear
  anywhere in what the writer was shown. These are candidates, not findings.
  "Oct. 19" against a source that says "October 19" is handled, but a model
  writing "European" from a source that says "Europe" will still be listed.
  The report lists every candidate with its sentence so a person can mark
  which ones are real.

It calls the API and costs money (roughly $0.005 per article on Haiku 4.5,
less on 5.5). It never writes to the lake. Run with --dry-run first to see
the stories it would use.

    uv run python scripts/writer_eval.py --days 10 --dry-run
    uv run python scripts/writer_eval.py --days 10
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pyiceberg.exceptions import NoSuchTableError  # noqa: E402
from pyiceberg.expressions import EqualTo  # noqa: E402

from src.adapters.base import RawItem  # noqa: E402
from src.editor import readability, run_writers  # noqa: E402

EDITIONS_DIR = REPO_ROOT / "site" / "content" / "editions"
DEFAULT_OUT = REPO_ROOT / "eval-out" / "writer"
READABILITY_LIMIT = 9.0

DEFAULT_ARMS = [
    "haiku-4-5=claude-haiku-4-5-20251001",
    "haiku-5-5=claude-haiku-5-5:medium:8192",
]


# --------------------------------------------------------------------------
# Grounding check: deterministic, so it is tested (tests/test_writer_eval.py)
# --------------------------------------------------------------------------
_NUMBER = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")
_NAME = re.compile(r"\b[A-Z][A-Za-z.'’-]*")
_WORD = re.compile(r"[A-Za-z][A-Za-z.'’-]*")

_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20",
}
_MONTHS = {
    "jan": "january", "feb": "february", "mar": "march", "apr": "april",
    "jun": "june", "jul": "july", "aug": "august", "sep": "september",
    "sept": "september", "oct": "october", "nov": "november", "dec": "december",
}


def _norm_word(token: str) -> str:
    """Lowercase, no possessive, no dots: "Trump's" -> "trump", "U.S." -> "us"."""
    word = token.lower().replace("’", "'")
    if word.endswith("'s"):
        word = word[:-2]
    word = word.replace(".", "").strip("'-")
    return _MONTHS.get(word, word)


def _norm_number(token: str) -> str:
    """ "$1,200.50%" -> "1200.50", "02" -> "2". Trailing punctuation is dropped.

    Leading zeros go so a prior mention dated 2026-10-02 grounds "October 2".
    """
    number = token.strip("$%").replace(",", "").rstrip(".")
    return number.lstrip("0") or number


@dataclass(frozen=True)
class Candidate:
    kind: str  # "number" or "name"
    token: str
    sentence: str


def source_vocabulary(source_text: str) -> tuple[set[str], set[str]]:
    """The words and numbers the writer was shown, normalised for matching."""
    words = {_norm_word(w) for w in _WORD.findall(source_text)}
    numbers = {_norm_number(n) for n in _NUMBER.findall(source_text)}
    numbers |= {digit for word, digit in _NUMBER_WORDS.items() if word in words}
    return words, numbers


def ungrounded_candidates(article_text: str, source_text: str) -> list[Candidate]:
    """Numbers and names in the article that the source never mentions.

    A name is any capitalised word that does not start its sentence, since a
    sentence-initial word is capitalised whether or not it is a name. A
    multi-word name ("World Nuclear Industry") is checked word by word, so
    one invented word in it is enough to list it.
    """
    words, numbers = source_vocabulary(source_text)
    found: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    for sentence in readability.split_sentences(article_text):
        for match in _NUMBER.finditer(sentence):
            token = _norm_number(match.group())
            if token and token not in numbers and ("number", token) not in seen:
                seen.add(("number", token))
                found.append(Candidate("number", match.group().rstrip(".,"), sentence))
        first = _WORD.search(sentence)
        for match in _NAME.finditer(sentence):
            if first is not None and match.start() == first.start():
                continue
            token = _norm_word(match.group())
            if len(token) > 1 and token not in words and ("name", token) not in seen:
                seen.add(("name", token))
                found.append(Candidate("name", match.group().rstrip(".,"), sentence))
    return found


def article_text(article: dict) -> str:
    return " ".join(article[k] for k in ("background", "what_happened", "why_it_matters"))


# --------------------------------------------------------------------------
# Arms: which model, and optionally the effort and output cap to send
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Arm:
    label: str
    model: str
    effort: str | None = None
    max_tokens: int | None = None


def parse_arm(spec: str) -> Arm:
    """ "label=model[:effort[:max_tokens]]", e.g. "haiku-5-5=claude-haiku-5-5:medium:8192"."""
    label, sep, rest = spec.partition("=")
    if not sep or not label or not rest:
        raise argparse.ArgumentTypeError(f"arm must be label=model[:effort[:max_tokens]], got {spec!r}")
    parts = rest.split(":")
    if len(parts) > 3:
        raise argparse.ArgumentTypeError(f"too many ':' parts in {spec!r}")
    model = parts[0]
    effort = parts[1] or None if len(parts) > 1 else None
    max_tokens = int(parts[2]) if len(parts) > 2 and parts[2] else None
    return Arm(label, model, effort, max_tokens)


class RecordingClient:
    """Passes calls through, applying the arm's effort and cap, and records each one.

    This is how the eval tests a setting without changing production code:
    the writer stage builds its request as it always does, and this layer
    adds what the arm asks for on the way out.
    """

    def __init__(self, client, arm: Arm, log: list[dict]):
        self._client = client
        self._arm = arm
        self._log = log
        self._lock = threading.Lock()  # one client per arm, shared by its threads
        self.messages = self

    def create(self, **kwargs):
        if self._arm.max_tokens:
            kwargs["max_tokens"] = self._arm.max_tokens
        # The arm decides effort, not the repo config: the writer stage sends
        # config.writer_effort, which a Haiku 4.5 arm must not pass on.
        output_config = {k: v for k, v in kwargs.get("output_config", {}).items() if k != "effort"}
        if self._arm.effort:
            output_config["effort"] = self._arm.effort
        kwargs["output_config"] = output_config
        started = time.monotonic()
        response = self._client.messages.create(**kwargs)
        with self._lock:
            self._log.append({
                "seconds": time.monotonic() - started,
                "stop_reason": response.stop_reason,
                "output_tokens": response.usage.output_tokens,
                "max_tokens": kwargs["max_tokens"],
            })
        return response


# --------------------------------------------------------------------------
# Data: the editor's picks for a past day, rebuilt from gold
# --------------------------------------------------------------------------
def pick_days(days: int, end: date | None) -> list[dict]:
    """The most recent editions with articles (fallbacks have none), oldest first."""
    editions = []
    for path in sorted(EDITIONS_DIR.glob("*.json"), reverse=True):
        edition = json.loads(path.read_text())
        day = date.fromisoformat(edition["date"])
        if end and day > end:
            continue
        if edition.get("edition_type") == "fallback":
            continue
        editions.append(edition)
        if len(editions) == days:
            break
    return list(reversed(editions))


def _scan(catalog, names: tuple[str, ...], day: date) -> list[dict]:
    """Rows for one ingest_date from the first table that has any."""
    for name in names:
        try:
            table = catalog.load_table(name)
        except NoSuchTableError:
            continue
        rows = table.scan(row_filter=EqualTo("ingest_date", day)).to_arrow().to_pylist()
        if rows:
            return rows
    return []


def load_day(catalog, edition: dict):
    """The writer's inputs for one edition: (contexts, prior mentions)."""
    from src.editor.context import build_contexts, retrieve_prior_mentions_batch

    day = date.fromisoformat(edition["date"])
    # Gold once archived, the live partition for a day not yet archived.
    items = [RawItem(**r) for r in _scan(catalog, ("gold.raw_items", "bronze.raw_items"), day)]
    clusters = {r["cluster_id"]: r for r in _scan(catalog, ("gold.story_clusters", "silver.story_clusters"), day)}
    picked = {s["cluster_id"] for section in edition["sections"] for s in section["stories"]}
    contexts = [c for c in build_contexts(clusters, items) if c.cluster_id in picked]
    prior = retrieve_prior_mentions_batch(contexts, day, catalog)
    return contexts, prior


# --------------------------------------------------------------------------
# Run and report
# --------------------------------------------------------------------------
def run(args) -> int:
    from src.config import get_pipeline
    from src.storage import get_catalog

    config = get_pipeline().editor
    catalog = get_catalog()
    editions = pick_days(args.days, args.end)
    if not editions:
        print("no editions with articles found")
        return 1

    work = []  # (day, context, prior mentions)
    for edition in editions:
        contexts, prior = load_day(catalog, edition)
        grounded = [c for c in contexts if c.grounding_chars >= config.min_grounding_chars]
        print(f"{edition['date']}: {len(contexts)} picked stories found, {len(grounded)} above the grounding floor")
        if args.stories_per_day:
            grounded = grounded[: args.stories_per_day]
        day = date.fromisoformat(edition["date"])
        work += [(day, ctx, prior.get(ctx.cluster_id, [])) for ctx in grounded]

    print(f"\n{len(work)} stories x {len(args.arm)} models = {len(work) * len(args.arm)} articles")
    if args.dry_run:
        for day, ctx, _ in work:
            print(f"  {day} {ctx.headline[:80]}")
        return 0

    client = run_writers.llm.get_client()
    system_prompt = run_writers.load_system_prompt()
    results: list[dict] = []
    calls: dict[str, list[dict]] = {arm.label: [] for arm in args.arm}
    recorders = {arm.label: RecordingClient(client, arm, calls[arm.label]) for arm in args.arm}
    lock = threading.Lock()

    def write(arm: Arm, day: date, ctx, prior: list[dict]) -> None:
        arm_config = config.model_copy(update={"writer_model": arm.model})
        result = run_writers.write_one(
            recorders[arm.label], ctx, arm_config, system_prompt, day,
            prior_mentions={ctx.cluster_id: prior},
        )
        source = run_writers.build_user_message(ctx, prior)
        row = {
            "arm": arm.label, "date": day.isoformat(), "cluster_id": ctx.cluster_id,
            "headline": ctx.headline, "status": result.status, "cost_usd": result.cost_usd,
            "article": result.article,
        }
        if result.article:
            text = article_text(result.article)
            row["grade"] = readability.grade(text)
            row["words"] = len(text.split())
            row["candidates"] = [c.__dict__ for c in ungrounded_candidates(text, source)]
        with lock:
            results.append(row)
            print(f"  {len(results)}/{len(work) * len(args.arm)}", end="\r", flush=True)

    with ThreadPoolExecutor(config.writer_concurrency) as pool:
        futures = [pool.submit(write, arm, day, ctx, prior) for day, ctx, prior in work for arm in args.arm]
        for future in futures:
            future.result()
    print()

    out = args.out / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps({"arms": [a.__dict__ for a in args.arm],
                                                  "results": results, "calls": calls}, indent=1))
    (out / "report.md").write_text(render_report(args.arm, results, calls, editions))
    print(f"report: {out / 'report.md'}")
    return 0


def summarize(rows: list[dict], calls: list[dict]) -> dict:
    written = [r for r in rows if r["status"] == "written"]
    grades = [r["grade"] for r in written]
    flagged = [len(r["candidates"]) for r in written]
    return {
        "stories": len(rows),
        "written": len(written),
        "failed": sum(r["status"] == "failed_validation" for r in rows),
        "calls": len(calls),
        "cap_hits": sum(c["stop_reason"] == "max_tokens" for c in calls),
        "grade_median": statistics.median(grades) if grades else None,
        "over_limit": sum(g > READABILITY_LIMIT for g in grades),
        "words_median": statistics.median([r["words"] for r in written]) if written else None,
        "candidates": sum(flagged),
        "articles_flagged": sum(n > 0 for n in flagged),
        "cost_usd": sum(r["cost_usd"] for r in rows),
        "seconds_median": statistics.median([c["seconds"] for c in calls]) if calls else None,
    }


def render_report(arms: list[Arm], results: list[dict], calls: dict, editions: list[dict]) -> str:
    lines = [
        "# Writer model eval",
        "",
        f"Editions {editions[0]['date']} to {editions[-1]['date']} "
        f"({len(editions)} {'day' if len(editions) == 1 else 'days'}). "
        "Each model wrote the same stories from the same inputs.",
        "",
        "| | " + " | ".join(a.label for a in arms) + " |",
        "|---|" + "---|" * len(arms),
    ]
    stats = {a.label: summarize([r for r in results if r["arm"] == a.label], calls[a.label]) for a in arms}

    def row(name, fmt):
        lines.append(f"| {name} | " + " | ".join(fmt(stats[a.label]) for a in arms) + " |")

    lines.append("| Model | " + " | ".join(
        f"`{a.model}`" + (f" ({a.effort})" if a.effort else "") for a in arms) + " |")
    row("Articles written", lambda s: f"{s['written']} / {s['stories']}")
    row("Failed validation twice", lambda s: str(s["failed"]))
    row("Calls (includes retries)", lambda s: str(s["calls"]))
    row("Stopped at the output cap", lambda s: str(s["cap_hits"]))
    row("Median grade, first draft", lambda s: f"{s['grade_median']:.1f}" if s["grade_median"] else "-")
    row(f"Over grade {READABILITY_LIMIT:g}", lambda s: f"{s['over_limit']} / {s['written']}")
    row("Median words", lambda s: f"{s['words_median']:.0f}" if s["words_median"] else "-")
    row("Grounding candidates", lambda s: str(s["candidates"]))
    row("Articles with any candidate", lambda s: f"{s['articles_flagged']} / {s['written']}")
    row("Cost", lambda s: f"${s['cost_usd']:.3f}")
    row("Median seconds per call", lambda s: f"{s['seconds_median']:.1f}" if s["seconds_median"] else "-")

    lines += [
        "",
        "Grades are per article. The production gate scores the whole edition,",
        "so these say which model needs fewer revision passes, not the exact count.",
        "",
        "## Grounding candidates to review",
        "",
        "Each line is a number or name in an article that does not appear in what",
        "the writer was shown. Tick the ones that are real additions. Most will be",
        "harmless (a word form the source used differently); the ones that matter",
        "are facts the model supplied from its own knowledge.",
        "",
    ]
    by_story: dict[tuple[str, str], list[dict]] = {}
    for r in results:
        by_story.setdefault((r["date"], r["cluster_id"]), []).append(r)
    for (day, _), rows in sorted(by_story.items()):
        if not any(r.get("candidates") for r in rows):
            continue
        lines.append(f"### {day}: {rows[0]['headline']}")
        for r in sorted(rows, key=lambda r: r["arm"]):
            for c in r.get("candidates", []):
                lines.append(f"- [ ] **{r['arm']}** `{c['token']}` ({c['kind']}): {c['sentence']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=10, help="most recent editions with articles (default 10)")
    parser.add_argument("--end", type=date.fromisoformat, help="last edition date to include (default: newest)")
    parser.add_argument("--stories-per-day", type=int, help="cap stories per day (default: all the editor picked)")
    parser.add_argument("--arm", type=parse_arm, action="append",
                        help="label=model[:effort[:max_tokens]], repeatable (default: Haiku 4.5 vs 5.5)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--dry-run", action="store_true", help="list the stories, make no API calls")
    args = parser.parse_args(argv)
    args.arm = args.arm or [parse_arm(a) for a in DEFAULT_ARMS]
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
