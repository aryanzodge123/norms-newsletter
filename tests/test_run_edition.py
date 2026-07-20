"""Edition assembly and the full run (SPEC 6.5).

Assembly is the deterministic seam between the two AI stages and the
validated artifact, so it is tested directly. The full run is tested with
Anthropic stubbed and Iceberg on a local sqlite catalog, the same offline
setup as the rest of the suite.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from src.config import EditorConfig
from src.editor import assemble, run_edition
from src.editor.context import StoryContext
from src.editor.run_writers import ArticleResult
from src.editor.schema import EditorResponse, EditionInvalid, validate_edition

from tests.conftest import make_item
from tests.test_writer_stage import FakeClient, valid_article


TODAY = date(2026, 7, 19)


def ctx(cluster_id, *, topic="Tech", score=7, headline=None, url=None, source="hackernews", body="x" * 500):
    url = url or f"https://x.invalid/{cluster_id}"
    item = make_item(url, source=source, body=body, title=headline or f"Headline {cluster_id}")
    return StoryContext(
        cluster_id=cluster_id,
        headline=headline or f"Headline {cluster_id}",
        summary_seed="Seed text.",
        topic=topic,
        score=score,
        rationale="because",
        confidence=0.7,
        member_count=1,
        members=(item,),
    )


def editor_response(sections, *, headline="The big story today", key_points=None, briefly=None):
    return EditorResponse(
        headline_of_the_day=headline,
        key_points=key_points
        or [
            {"text": "Point one about the day.", "topic": "Tech"},
            {"text": "Point two about the day.", "topic": "Tech"},
            {"text": "Point three about the day.", "topic": "Science"},
            {"text": "Point four about the day.", "topic": "Science"},
        ],
        sections=sections,
        briefly=briefly or [],
    )


# --------------------------------------------------------------------------
# assemble_edition
# --------------------------------------------------------------------------
def test_assemble_produces_a_valid_edition(tmp_path):
    contexts = [
        ctx("a" * 32, topic="Tech"),
        ctx("b" * 32, topic="Tech"),
        ctx("c" * 32, topic="Science"),
        ctx("d" * 32, topic="Science"),
    ]
    editor = editor_response(
        [
            {"name": "Technology", "stories": [
                {"cluster_id": "a" * 32, "title": "First tech story", "summary": "It happened here."},
                {"cluster_id": "b" * 32, "title": "Second tech story", "summary": "It happened there."},
            ]},
            {"name": "Science", "stories": [
                {"cluster_id": "c" * 32, "title": "First science story", "summary": "A discovery."},
                {"cluster_id": "d" * 32, "title": "Second science story", "summary": "Another one."},
            ]},
        ]
    )
    articles = {c.cluster_id: ArticleResult(c.cluster_id, json.loads(valid_article()), 0.001, "written") for c in contexts}

    edition = assemble.assemble_edition(
        editor=editor,
        articles=articles,
        contexts=contexts,
        edition_type="normal",
        target_date=TODAY,
        items_ingested=200,
        clusters_considered=50,
        sections_held=1,
        editions_dir=tmp_path,
    )
    validate_edition(edition)  # raises if wrong
    assert edition["edition_number"] == 1
    assert edition["stats"]["stories_run"] == 4
    assert [s["name"] for s in edition["sections"]] == ["Technology", "Science"]


def test_single_story_section_collapses_into_briefly(tmp_path):
    """SPEC 6.5: a section that cannot field two stories collapses into
    briefly. The editor cannot be held to this structurally (the API's
    structured-output subset rejects minItems above 1), so code enforces it
    and the edition survives instead of falling back."""
    contexts = [
        ctx("a" * 32, topic="Tech"),
        ctx("b" * 32, topic="Tech"),
        ctx("c" * 32, topic="Science", headline="Lonely science story"),
    ]
    editor = editor_response(
        [
            {"name": "Technology", "stories": [
                {"cluster_id": "a" * 32, "title": "First tech story", "summary": "It happened."},
                {"cluster_id": "b" * 32, "title": "Second tech story", "summary": "So did this."},
            ]},
            # Only one story: invalid as a section, must become a briefly item.
            {"name": "Science", "stories": [
                {"cluster_id": "c" * 32, "title": "Lonely science story", "summary": "Alone."},
            ]},
        ]
    )
    edition = assemble.assemble_edition(
        editor=editor, articles={}, contexts=contexts, edition_type="normal",
        target_date=TODAY, items_ingested=10, clusters_considered=3,
        sections_held=0, editions_dir=tmp_path,
    )
    validate_edition(edition)
    assert [s["name"] for s in edition["sections"]] == ["Technology"]
    assert "Lonely science story" in [b["title"] for b in edition["briefly"]]
    assert edition["stats"]["stories_run"] == 2


def test_invented_section_name_is_dropped_not_fatal(tmp_path):
    """The model sometimes invents a section name, including a literal
    "briefly" section. Code drops it and keeps the edition."""
    contexts = [
        ctx("a" * 32, topic="Tech"),
        ctx("b" * 32, topic="Tech"),
        ctx("c" * 32, topic="Science", headline="Spilled story"),
    ]
    editor = editor_response(
        [
            {"name": "Technology", "stories": [
                {"cluster_id": "a" * 32, "title": "First tech story", "summary": "It happened."},
                {"cluster_id": "b" * 32, "title": "Second tech story", "summary": "So did this."},
            ]},
            {"name": "briefly", "stories": [
                {"cluster_id": "c" * 32, "title": "Spilled story", "summary": "Not a real section."},
            ]},
        ]
    )
    edition = assemble.assemble_edition(
        editor=editor, articles={}, contexts=contexts, edition_type="normal",
        target_date=TODAY, items_ingested=10, clusters_considered=3,
        sections_held=0, editions_dir=tmp_path,
    )
    validate_edition(edition)
    assert [s["name"] for s in edition["sections"]] == ["Technology"]
    assert "Spilled story" in [b["title"] for b in edition["briefly"]]


def test_empty_section_is_dropped(tmp_path):
    contexts = [ctx("a" * 32, topic="Tech"), ctx("b" * 32, topic="Tech")]
    editor = editor_response(
        [
            {"name": "Technology", "stories": [
                {"cluster_id": "a" * 32, "title": "One", "summary": "First."},
                {"cluster_id": "b" * 32, "title": "Two", "summary": "Second."},
            ]},
            {"name": "Science", "stories": []},
        ]
    )
    edition = assemble.assemble_edition(
        editor=editor, articles={}, contexts=contexts, edition_type="normal",
        target_date=TODAY, items_ingested=10, clusters_considered=2,
        sections_held=0, editions_dir=tmp_path,
    )
    validate_edition(edition)
    assert [s["name"] for s in edition["sections"]] == ["Technology"]


def test_scores_come_from_the_pipeline_not_the_editor(tmp_path):
    contexts = [ctx("a" * 32, score=9), ctx("b" * 32, score=3)]
    editor = editor_response(
        [{"name": "Technology", "stories": [
            {"cluster_id": "a" * 32, "title": "One", "summary": "First."},
            {"cluster_id": "b" * 32, "title": "Two", "summary": "Second."},
        ]}]
    )
    edition = assemble.assemble_edition(
        editor=editor, articles={}, contexts=contexts, edition_type="normal",
        target_date=TODAY, items_ingested=1, clusters_considered=2,
        sections_held=0, editions_dir=tmp_path,
    )
    scores = {s["cluster_id"]: s["score"] for s in edition["sections"][0]["stories"]}
    assert scores == {"a" * 32: 9, "b" * 32: 3}


def test_null_article_carried_through(tmp_path):
    contexts = [ctx("a" * 32), ctx("b" * 32)]
    editor = editor_response(
        [{"name": "Technology", "stories": [
            {"cluster_id": "a" * 32, "title": "One", "summary": "First."},
            {"cluster_id": "b" * 32, "title": "Two", "summary": "Second."},
        ]}]
    )
    articles = {"a" * 32: ArticleResult("a" * 32, None, 0.0, "skipped_grounding")}
    edition = assemble.assemble_edition(
        editor=editor, articles=articles, contexts=contexts, edition_type="normal",
        target_date=TODAY, items_ingested=1, clusters_considered=2,
        sections_held=0, editions_dir=tmp_path,
    )
    a = next(s for s in edition["sections"][0]["stories"] if s["cluster_id"] == "a" * 32)
    assert a["article"] is None


def test_editor_selecting_an_unoffered_cluster_is_rejected(tmp_path):
    contexts = [ctx("a" * 32), ctx("b" * 32)]
    editor = editor_response(
        [{"name": "Technology", "stories": [
            {"cluster_id": "a" * 32, "title": "One", "summary": "First."},
            {"cluster_id": "z" * 32, "title": "Ghost", "summary": "Not offered."},
        ]}]
    )
    with pytest.raises(EditionInvalid):
        assemble.assemble_edition(
            editor=editor, articles={}, contexts=contexts, edition_type="normal",
            target_date=TODAY, items_ingested=1, clusters_considered=2,
            sections_held=0, editions_dir=tmp_path,
        )


def test_briefly_resolves_ids_to_links(tmp_path):
    contexts = [ctx("a" * 32), ctx("b" * 32), ctx("e" * 32, topic="Finance", url="https://x.invalid/e")]
    editor = editor_response(
        [{"name": "Technology", "stories": [
            {"cluster_id": "a" * 32, "title": "One", "summary": "First."},
            {"cluster_id": "b" * 32, "title": "Two", "summary": "Second."},
        ]}],
        briefly=["e" * 32],
    )
    edition = assemble.assemble_edition(
        editor=editor, articles={}, contexts=contexts, edition_type="normal",
        target_date=TODAY, items_ingested=1, clusters_considered=3,
        sections_held=0, editions_dir=tmp_path,
    )
    assert edition["briefly"] == [
        {"title": "Headline " + "e" * 32, "url": "https://x.invalid/e", "topic": "Finance"}
    ]


# --------------------------------------------------------------------------
# assemble_fallback (SPEC section 7)
# --------------------------------------------------------------------------
def test_fallback_takes_top_ten_by_score(tmp_path):
    contexts = [ctx(f"{i:032d}", score=(20 - i) % 10 + 1) for i in range(15)]
    contexts.sort(key=lambda c: -c.score)
    edition = assemble.assemble_fallback(
        contexts=contexts, target_date=TODAY, notice="Short one today.", editions_dir=tmp_path,
    )
    validate_edition(edition)
    assert len(edition["stories"]) == 10
    assert [s["rank"] for s in edition["stories"]] == list(range(1, 11))
    scores = [s["score"] for s in edition["stories"]]
    assert scores == sorted(scores, reverse=True)


def test_fallback_with_no_stories_is_valid(tmp_path):
    """SPEC 7 / decision #8: never skip a day silently. With nothing usable
    at all the page is the notice alone, rather than a failed publish."""
    edition = assemble.assemble_fallback(
        contexts=[], target_date=TODAY, notice="Nothing to report today.", editions_dir=tmp_path,
    )
    validate_edition(edition)
    assert edition["stories"] == []


# --------------------------------------------------------------------------
# The full run, offline
# --------------------------------------------------------------------------
def _seed_partitions(catalog, ingest_date, contexts):
    """Write bronze items and silver rows so run() can read a real day."""
    from src import bronze
    from src.silver import table as silver_table

    items = [c.members[0] for c in contexts]
    bronze.append_items(bronze.ensure_table(catalog), items)

    rows = []
    for c in contexts:
        rows.append({
            "cluster_id": c.cluster_id,
            "ingest_date": ingest_date,
            "topic": c.topic,
            "headline": c.headline,
            "summary_seed": c.summary_seed,
            "member_ids": [m.item_id for m in c.members],
            "member_count": c.member_count,
            "sources": sorted({m.source for m in c.members}),
            "score": c.score,
            "rationale": c.rationale,
            "confidence": c.confidence,
            "model_version": "claude-haiku-4-5-20251001",
            "prompt_version": "scoring_v1",
            "scored_at": datetime.now(UTC),
        })
    table = silver_table.ensure_table(catalog)
    silver_table.overwrite_partition(table, ingest_date, rows)


@pytest.fixture
def wired(monkeypatch, local_catalog, tmp_path):
    """Point storage, editions dir, and config at test doubles."""
    monkeypatch.setattr(run_edition, "get_catalog", lambda: local_catalog)
    monkeypatch.setattr("src.bronze.get_catalog", lambda: local_catalog, raising=False)
    editions = tmp_path / "editions"
    monkeypatch.setattr(run_edition, "OUTPUT_DIR", editions)
    monkeypatch.setattr(assemble, "next_edition_number", lambda d, _=None: 1)

    cfg = EditorConfig(
        editor_model="claude-sonnet-4-5-20250929",
        writer_model="claude-haiku-4-5-20251001",
        max_retries=1,
        writer_concurrency=4,
        min_grounding_chars=400,
        min_clusters_for_normal=4,
        min_clusters_for_quiet=2,
    )

    class _Pipeline:
        editor = cfg

    monkeypatch.setattr(run_edition, "get_pipeline", lambda: _Pipeline())
    return local_catalog, editions


def test_rerun_after_archival_keeps_the_published_edition(wired, monkeypatch):
    """SPEC 6.9 drops the day's partitions after a successful publish, so a
    same-day re-run reads an empty day. It must keep what was published
    (decision #17), not replace it with an empty fallback."""
    catalog, editions = wired
    editions.mkdir(parents=True, exist_ok=True)
    published = editions / f"{TODAY.isoformat()}.json"
    original = json.dumps({"edition_type": "normal", "marker": "the real edition"})
    published.write_text(original)

    # No partitions seeded: this is the post-archival state.
    called = {"client": False}
    monkeypatch.setattr(run_edition, "get_client", lambda: called.__setitem__("client", True))

    rc = run_edition.run(TODAY)

    assert rc == 0
    assert published.read_text() == original  # untouched
    assert called["client"] is False  # and no AI spend on a no-op re-run


def test_full_run_writes_a_normal_edition(wired, monkeypatch):
    catalog, editions = wired
    contexts = [
        ctx("a" * 32, topic="Tech", url="https://x.invalid/a"),
        ctx("b" * 32, topic="Tech", url="https://x.invalid/b"),
        ctx("c" * 32, topic="Science", url="https://x.invalid/c"),
        ctx("d" * 32, topic="Science", url="https://x.invalid/d"),
    ]
    _seed_partitions(catalog, TODAY, contexts)

    editor_json = json.dumps({
        "headline_of_the_day": "The big story of the day here",
        "key_points": [
            {"text": "A first plain point about today.", "topic": "Tech"},
            {"text": "A second plain point about today.", "topic": "Tech"},
            {"text": "A third plain point about today.", "topic": "Science"},
            {"text": "A fourth plain point about today.", "topic": "Science"},
        ],
        "sections": [
            {"name": "Technology", "stories": [
                {"cluster_id": "a" * 32, "title": "First tech story", "summary": "A clear thing."},
                {"cluster_id": "b" * 32, "title": "Second tech story", "summary": "Another clear thing."},
            ]},
            {"name": "Science", "stories": [
                {"cluster_id": "c" * 32, "title": "First science story", "summary": "A find."},
                {"cluster_id": "d" * 32, "title": "Second science story", "summary": "A second find."},
            ]},
        ],
        "briefly": [],
    })
    # one editor call, then four writer calls (all articles simple/plain)
    replies = [editor_json] + [valid_article() for _ in range(4)]
    monkeypatch.setattr(run_edition, "get_client", lambda: FakeClient(replies))

    rc = run_edition.run(TODAY)
    assert rc == 0
    path = editions / f"{TODAY.isoformat()}.json"
    edition = json.loads(path.read_text())
    validate_edition(edition)
    assert edition["edition_type"] == "normal"
    assert edition["stats"]["stories_run"] == 4


def test_full_run_falls_back_when_editor_fails_twice(wired, monkeypatch):
    catalog, editions = wired
    contexts = [ctx(f"{i:032d}", score=9 - i) for i in range(5)]
    _seed_partitions(catalog, TODAY, contexts)

    # editor invalid twice -> fallback. No writer calls follow.
    monkeypatch.setattr(run_edition, "get_client", lambda: FakeClient(["nope", "still nope"]))

    rc = run_edition.run(TODAY)
    assert rc == 0
    edition = json.loads((editions / f"{TODAY.isoformat()}.json").read_text())
    validate_edition(edition)
    assert edition["edition_type"] == "fallback"
    assert len(edition["stories"]) == 5


def test_thin_day_produces_fallback_without_calling_the_model(wired, monkeypatch):
    catalog, editions = wired
    # one usable cluster, below min_clusters_for_quiet (2)
    _seed_partitions(catalog, TODAY, [ctx("a" * 32)])

    class Boom(FakeClient):
        def __init__(self):
            super().__init__([])

    monkeypatch.setattr(run_edition, "get_client", lambda: Boom())
    rc = run_edition.run(TODAY)
    assert rc == 0
    edition = json.loads((editions / f"{TODAY.isoformat()}.json").read_text())
    assert edition["edition_type"] == "fallback"


HARD = (
    "Institutional recalibration necessitated comprehensive reconfiguration "
    "throughout numerous interdependent administrative subdivisions "
    "simultaneously."
)


def _hard_edition():
    return {
        "date": TODAY.isoformat(),
        "edition_number": 1,
        "edition_type": "normal",
        "headline_of_the_day": "A dense edition today",
        "key_points": [
            {"text": "A first plain point.", "topic": "Tech"},
            {"text": "A second plain point.", "topic": "Tech"},
            {"text": "A third plain point.", "topic": "Tech"},
            {"text": "A fourth plain point.", "topic": "Tech"},
        ],
        "audio": None,
        "sections": [
            {"name": "Technology", "stories": [
                {"cluster_id": "a" * 32, "slug": "hard", "title": "One", "summary": HARD,
                 "score": 7, "sources": [{"name": "hn", "url": "https://x.invalid/a"}],
                 "article": {"background": HARD, "what_happened": HARD, "why_it_matters": HARD, "quote": None}},
                {"cluster_id": "b" * 32, "slug": "easy", "title": "Two",
                 "summary": "The dog ran. The cat sat. We had a good day.",
                 "score": 6, "sources": [{"name": "hn", "url": "https://x.invalid/b"}],
                 "article": None},
            ]},
        ],
        "briefly": [],
        "stats": {"items_ingested": 1, "clusters_considered": 2, "stories_run": 2, "sources": 1, "sections_held": 0},
    }


def test_revision_pass_fixes_a_hard_edition(monkeypatch):
    cfg = EditorConfig(
        editor_model="claude-sonnet-4-5-20250929", writer_model="claude-haiku-4-5-20251001",
        max_retries=1, writer_concurrency=4, min_grounding_chars=400,
        min_clusters_for_normal=4, min_clusters_for_quiet=2,
    )
    edition = _hard_edition()
    contexts_by_id = {"a" * 32: ctx("a" * 32)}
    # revised article reads easily
    easy = json.dumps({
        "background": "The dog ran.", "what_happened": "The cat sat.",
        "why_it_matters": "We had a good day.", "quote": None,
    })
    # The revision pass now simplifies the editor's own text first (its
    # summaries and glance points are measured by the gate too), then
    # re-calls the writer for the failing story.
    simplified = json.dumps({"items": [
        {"id": "headline", "text": "The dog ran fast."},
        {"id": "point:0", "text": "The dog ran."},
        {"id": "summary:hard", "text": "The cat sat down."},
    ]})
    client = FakeClient([simplified, easy])
    edition, cost, flag = run_edition._revise_for_readability(
        client, edition, contexts_by_id, cfg, "system", TODAY
    )
    assert flag is False           # gate now passes
    assert client.messages.calls == 2  # one simplify call, one story re-called
    assert edition["sections"][0]["stories"][0]["summary"] == "The cat sat down."


def test_revision_stops_early_once_the_gate_passes(monkeypatch):
    """The loop is bounded by readability_max_passes but must not spend a
    second pass on an edition that is already under the limit."""
    cfg = EditorConfig(
        editor_model="claude-sonnet-4-5-20250929", writer_model="claude-haiku-4-5-20251001",
        max_retries=1, writer_concurrency=4, min_grounding_chars=400,
        min_clusters_for_normal=4, min_clusters_for_quiet=2, readability_max_passes=3,
    )
    edition = _hard_edition()
    contexts_by_id = {"a" * 32: ctx("a" * 32)}
    simplified = json.dumps({"items": [
        {"id": "headline", "text": "The dog ran fast."},
        {"id": "point:0", "text": "The dog ran."},
        {"id": "summary:hard", "text": "The cat sat down."},
    ]})
    easy = json.dumps({
        "background": "The dog ran.", "what_happened": "The cat sat.",
        "why_it_matters": "We had a good day.", "quote": None,
    })
    client = FakeClient([simplified, easy])
    _, _, flag = run_edition._revise_for_readability(
        client, edition, contexts_by_id, cfg, "system", TODAY
    )
    assert flag is False
    # One pass was enough, so the budget of 3 was not spent.
    assert client.messages.calls == 2


def test_revision_pass_flags_when_still_hard(monkeypatch):
    cfg = EditorConfig(
        editor_model="claude-sonnet-4-5-20250929", writer_model="claude-haiku-4-5-20251001",
        max_retries=1, writer_concurrency=4, min_grounding_chars=400,
        min_clusters_for_normal=4, min_clusters_for_quiet=2,
    )
    edition = _hard_edition()
    contexts_by_id = {"a" * 32: ctx("a" * 32)}
    # the "revision" comes back just as hard
    still_hard = json.dumps({
        "background": HARD, "what_happened": HARD, "why_it_matters": HARD, "quote": None,
    })
    client = FakeClient([still_hard])
    edition, cost, flag = run_edition._revise_for_readability(
        client, edition, contexts_by_id, cfg, "system", TODAY
    )
    assert flag is True            # published anyway, flagged for review


def test_dry_run_writes_nothing_and_makes_no_calls(wired, monkeypatch):
    catalog, editions = wired
    contexts = [ctx(f"{i:032d}") for i in range(4)]
    _seed_partitions(catalog, TODAY, contexts)

    def no_client():
        raise AssertionError("dry run must not build a client")

    monkeypatch.setattr(run_edition, "get_client", no_client)
    rc = run_edition.run(TODAY, dry_run=True)
    assert rc == 0
    assert not (editions / f"{TODAY.isoformat()}.json").exists()
