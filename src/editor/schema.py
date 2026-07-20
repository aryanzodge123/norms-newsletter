"""The edition.json schema (SPEC 6.5), canonical for SPEC and DESIGN both.

Written before either prompt, per rule zero (SPEC section 2). This module,
not the prompt and not the model, is the authority on what a valid edition
is. The editor and writer prompts are asked to produce output matching
schemas *derived from here* so the two can never drift apart.

The gate in .claude/skills/milestone-verify imports this module and will
use either entry point:

  validate_edition(obj) -> Edition   raises EditionInvalid on anything bad
  EDITION_SCHEMA                     JSON Schema dict

SPEC 6.5's JSON block shows the shape but states several constraints only
in prose around it. Those live here as validators, each with the sentence
it comes from, because a constraint that is only in prose is a constraint
that is not enforced.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

# The SPEC 6.5 section skeleton, in render order. These are the values the
# scoring stage already constrains `topic` to (src/silver/score.py), so
# assembling sections is a lookup rather than a mapping problem.
TOPICS = (
    "Tech",
    "AI",
    "Business",
    "Finance",
    "US Politics",
    "World",
    "Regulation",
    "Science",
    "Cyber",
)

# DESIGN.md SectionLabel: "Section names render in full ('Artificial
# intelligence', not 'AI')". SPEC 6.5's own example uses the full name as
# the `name` value, so the expansion belongs to the data, not the
# renderer. Deterministic code owns it; the editor agent is given the full
# names and never invents one.
SECTION_NAMES: dict[str, str] = {
    "Tech": "Technology",
    "AI": "Artificial intelligence",
    "Business": "Business",
    "Finance": "Finance",
    "US Politics": "US politics",
    "World": "World",
    "Regulation": "Regulation",
    "Science": "Science",
    "Cyber": "Cybersecurity",
}

SECTION_ORDER = tuple(SECTION_NAMES[topic] for topic in TOPICS)

EditionType = Literal["normal", "quiet", "fallback"]

# SPEC 6.5: "a quiet edition may include one point in Norm's voice tagged
# topic 'norm'". Allowed nowhere else, and never more than once.
NORM_TOPIC = "norm"

# SPEC 6.5 budget: "min 2 / max 4 per section".
MIN_STORIES_PER_SECTION = 2
MAX_STORIES_PER_SECTION = 4

# SPEC 6.5 budget: "Budget 15-20 stories". The upper bound is hard: it caps
# edition length and writer-stage cost. The lower bound is a target, not an
# invariant, because the same section also says "3+ dead sections -> shrink
# the edition" and a quiet day shrinks further still. Code checks the
# target and reports it; only the ceiling rejects.
TARGET_MIN_STORIES = 15
MAX_STORIES = 20

# SPEC 6.5: "4-6 points normal, 3 quiet".
KEY_POINTS_NORMAL = (4, 6)
KEY_POINTS_QUIET = (3, 3)

# SPEC 6.5: "Fallback editions carry only date, edition_number,
# edition_type, and a ranked top-10 stories list".
FALLBACK_STORIES = 10

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# CLAUDE.md rule 7 and voice standard 8. This is generated text, so the
# schema is the right place to catch an em dash rather than hoping the
# prompt held.
EM_DASH = "—"


class EditionInvalid(ValueError):
    """Raised when an object is not a valid edition."""


class Strict(BaseModel):
    """Rejects unknown keys, matching src/config.py and score.py."""

    model_config = ConfigDict(extra="forbid")


def _no_em_dash(value: str) -> str:
    if EM_DASH in value:
        raise ValueError(
            "em dash is not allowed in generated text (voice standard 8)"
        )
    return value


class Source(Strict):
    name: str = Field(min_length=1)
    url: str = Field(min_length=1)


class Quote(Strict):
    """SPEC 6.5 quote policy, decision #15.

    Only a person speaking, short, always attributed and linked. The length
    cap is lint-enforced per SPEC 6.5; it lives here so a quote that blows
    past it is rejected rather than trimmed silently.
    """

    text: str = Field(min_length=1, max_length=320)
    attribution: str = Field(min_length=1)
    source_url: str = Field(min_length=1)

    @field_validator("text", "attribution")
    @classmethod
    def _clean(cls, value: str) -> str:
        return _no_em_dash(value.strip())


class Article(Strict):
    """The expandable body of a story (decision #12, DESIGN.md StoryCard)."""

    background: str = Field(min_length=1)
    what_happened: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    quote: Quote | None = None

    @field_validator("background", "what_happened", "why_it_matters")
    @classmethod
    def _clean(cls, value: str) -> str:
        return _no_em_dash(value.strip())


class Story(Strict):
    cluster_id: str = Field(min_length=1)
    slug: str
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    score: int = Field(ge=1, le=10)
    sources: list[Source] = Field(min_length=1)
    # SPEC 6.5: nullable. A story whose article failed validation twice, or
    # whose cluster carried too little grounding to write from, publishes
    # as a collapsed card with no expand affordance.
    article: Article | None = None

    @field_validator("slug")
    @classmethod
    def _valid_slug(cls, value: str) -> str:
        if not SLUG_RE.match(value):
            raise ValueError(
                f"slug must be lowercase alphanumeric words joined by hyphens, got {value!r}"
            )
        return value

    @field_validator("title", "summary")
    @classmethod
    def _clean(cls, value: str) -> str:
        return _no_em_dash(value.strip())

    @model_validator(mode="after")
    def _quote_links_to_own_source(self) -> Story:
        """Decision #15: a quote is "always attributed and linked", and the
        link has to be to a source this story actually cites. Otherwise the
        model can attach a plausible URL nobody checked."""
        if self.article is None or self.article.quote is None:
            return self
        urls = {source.url for source in self.sources}
        if self.article.quote.source_url not in urls:
            raise ValueError(
                "quote.source_url must be one of the story's own source URLs"
            )
        return self


class Section(Strict):
    name: str
    stories: list[Story]

    @field_validator("name")
    @classmethod
    def _known_section(cls, value: str) -> str:
        if value not in SECTION_ORDER:
            raise ValueError(
                f"unknown section {value!r}, expected one of {list(SECTION_ORDER)}"
            )
        return value

    @model_validator(mode="after")
    def _section_budget(self) -> Section:
        """SPEC 6.5: min 2 / max 4 per section. A section that could only
        field one story is a dead section and collapses into briefly, so a
        one-story section in the output is a bug, not a thin day."""
        count = len(self.stories)
        if not MIN_STORIES_PER_SECTION <= count <= MAX_STORIES_PER_SECTION:
            raise ValueError(
                f"section {self.name!r} has {count} stories, expected "
                f"{MIN_STORIES_PER_SECTION} to {MAX_STORIES_PER_SECTION} "
                "(a section that cannot field 2 collapses into briefly)"
            )
        return self


class KeyPoint(Strict):
    text: str = Field(min_length=1)
    topic: str

    @field_validator("text")
    @classmethod
    def _clean(cls, value: str) -> str:
        return _no_em_dash(value.strip())

    @field_validator("topic")
    @classmethod
    def _known_topic(cls, value: str) -> str:
        if value not in TOPICS and value != NORM_TOPIC:
            raise ValueError(
                f"unknown key_point topic {value!r}, expected one of "
                f"{list(TOPICS)} or {NORM_TOPIC!r}"
            )
        return value


class BrieflyItem(Strict):
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    topic: str

    @field_validator("title")
    @classmethod
    def _clean(cls, value: str) -> str:
        return _no_em_dash(value.strip())

    @field_validator("topic")
    @classmethod
    def _known_topic(cls, value: str) -> str:
        if value not in TOPICS:
            raise ValueError(
                f"unknown briefly topic {value!r}, expected one of {list(TOPICS)}"
            )
        return value


class Audio(Strict):
    url: str = Field(min_length=1)
    duration_seconds: int = Field(gt=0)
    # SPEC 6.7 podcast feed: the RSS <enclosure> requires a byte length, and
    # podcast directories reject length="0". The audio build measures the
    # encoded MP3 and records it here so feed.xml derives a real length.
    # Proposed SPEC 6.5/6.7 addition (M6).
    size_bytes: int = Field(gt=0)


class Stats(Strict):
    items_ingested: int = Field(ge=0)
    clusters_considered: int = Field(ge=0)
    stories_run: int = Field(ge=0)
    sources: int = Field(ge=0)
    sections_held: int = Field(ge=0)


class RankedStory(Strict):
    """One row of a fallback edition's top-10 list (DESIGN.md RankedList)."""

    rank: int = Field(ge=1, le=FALLBACK_STORIES)
    title: str = Field(min_length=1)
    score: int = Field(ge=1, le=10)
    url: str = Field(min_length=1)
    source: str = Field(min_length=1)

    @field_validator("title")
    @classmethod
    def _clean(cls, value: str) -> str:
        return _no_em_dash(value.strip())


class _EditionBase(Strict):
    date: str
    edition_number: int = Field(ge=1)

    @field_validator("date")
    @classmethod
    def _iso_date(cls, value: str) -> str:
        if not DATE_RE.match(value):
            raise ValueError(f"date must be YYYY-MM-DD, got {value!r}")
        return value


class Edition(_EditionBase):
    """A normal or quiet edition. The full SPEC 6.5 shape."""

    edition_type: Literal["normal", "quiet"]
    headline_of_the_day: str = Field(min_length=1)
    key_points: list[KeyPoint]
    audio: Audio | None = None
    sections: list[Section]
    briefly: list[BrieflyItem] = Field(default_factory=list)
    stats: Stats

    @field_validator("headline_of_the_day")
    @classmethod
    def _clean(cls, value: str) -> str:
        return _no_em_dash(value.strip())

    @model_validator(mode="after")
    def _key_point_count(self) -> Edition:
        """SPEC 6.5: 4-6 points normal, 3 quiet."""
        low, high = KEY_POINTS_NORMAL if self.edition_type == "normal" else KEY_POINTS_QUIET
        count = len(self.key_points)
        if not low <= count <= high:
            raise ValueError(
                f"a {self.edition_type} edition needs {low} to {high} key_points, got {count}"
            )
        return self

    @model_validator(mode="after")
    def _norm_point_is_quiet_only(self) -> Edition:
        """SPEC 6.5: "a quiet edition may include one point in Norm's
        voice tagged topic 'norm'". One, and only on a quiet day."""
        norm_points = [p for p in self.key_points if p.topic == NORM_TOPIC]
        if not norm_points:
            return self
        if self.edition_type != "quiet":
            raise ValueError(
                f"a {NORM_TOPIC!r} key_point is only allowed on a quiet edition"
            )
        if len(norm_points) > 1:
            raise ValueError(
                f"at most one {NORM_TOPIC!r} key_point, got {len(norm_points)}"
            )
        return self

    @model_validator(mode="after")
    def _sections_present_and_ordered(self) -> Edition:
        if not self.sections:
            raise ValueError(
                "an edition needs at least one section; a day with none is a "
                "fallback or quiet edition, not an empty normal one"
            )
        names = [section.name for section in self.sections]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate section names: {names}")
        expected = [name for name in SECTION_ORDER if name in set(names)]
        if names != expected:
            raise ValueError(
                f"sections must follow the SPEC 6.5 skeleton order, got {names}"
            )
        return self

    @model_validator(mode="after")
    def _story_budget_and_uniqueness(self) -> Edition:
        stories = self.all_stories
        if len(stories) > MAX_STORIES:
            raise ValueError(
                f"{len(stories)} stories exceeds the SPEC 6.5 ceiling of {MAX_STORIES}"
            )
        slugs = [story.slug for story in stories]
        if len(set(slugs)) != len(slugs):
            raise ValueError("story slugs must be unique within an edition")
        cluster_ids = [story.cluster_id for story in stories]
        if len(set(cluster_ids)) != len(cluster_ids):
            raise ValueError("a cluster may appear in an edition only once")
        return self

    @model_validator(mode="after")
    def _briefly_does_not_repeat_stories(self) -> Edition:
        """Briefly carries what did not make a section (SPEC 6.5). A title
        in both places is the same story told twice."""
        titles = {story.title.casefold() for story in self.all_stories}
        repeated = [b.title for b in self.briefly if b.title.casefold() in titles]
        if repeated:
            raise ValueError(f"briefly repeats stories already in sections: {repeated}")
        return self

    @property
    def all_stories(self) -> list[Story]:
        return [story for section in self.sections for story in section.stories]

    @property
    def meets_story_target(self) -> bool:
        """The soft half of the SPEC 6.5 budget. Reported, never enforced:
        a shrunken or quiet edition legitimately falls short."""
        return len(self.all_stories) >= TARGET_MIN_STORIES


class FallbackEdition(_EditionBase):
    """SPEC section 7's abbreviated edition, decision #8.

    "Fallback editions carry only date, edition_number, edition_type, and a
    ranked top-10 stories list (title, score, primary source link)." The
    notice text is Norm's voice and is generated, so it lives here too;
    everything else the fallback page needs is in DESIGN.md's NoticeBanner
    and RankedList components.
    """

    edition_type: Literal["fallback"]
    notice: str = Field(min_length=1)
    stories: list[RankedStory] = Field(min_length=1, max_length=FALLBACK_STORIES)

    @field_validator("notice")
    @classmethod
    def _clean(cls, value: str) -> str:
        return _no_em_dash(value.strip())

    @model_validator(mode="after")
    def _ranked_contiguously(self) -> FallbackEdition:
        ranks = [story.rank for story in self.stories]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError(f"ranks must be 1..N in order, got {ranks}")
        scores = [story.score for story in self.stories]
        if scores != sorted(scores, reverse=True):
            raise ValueError("fallback stories must be ordered by score, highest first")
        return self


AnyEdition = Edition | FallbackEdition


def validate_edition(obj: dict) -> AnyEdition:
    """Validate one edition object. The gate's entry point.

    Dispatches on edition_type because a fallback edition is a genuinely
    different, smaller shape (SPEC 6.5), not a normal edition with fields
    left out.
    """
    if not isinstance(obj, dict):
        raise EditionInvalid(f"edition must be a JSON object, got {type(obj).__name__}")

    edition_type = obj.get("edition_type")
    if edition_type not in ("normal", "quiet", "fallback"):
        raise EditionInvalid(
            f"edition_type must be normal, quiet, or fallback, got {edition_type!r}"
        )

    model = FallbackEdition if edition_type == "fallback" else Edition
    try:
        return model(**obj)
    except ValidationError as exc:
        raise EditionInvalid(f"edition failed schema validation: {exc}") from exc


# ---------------------------------------------------------------------------
# JSON Schema, for the gate and for the API calls
# ---------------------------------------------------------------------------
# The two AI stages are constrained to schemas derived from the models
# above rather than to schemas written by hand. Same belt-and-braces as
# src/silver/score.py: the request asks for conforming output, and the
# models still validate every reply.

EDITION_SCHEMA: dict = {
    "oneOf": [
        Edition.model_json_schema(),
        FallbackEdition.model_json_schema(),
    ]
}


class EditorStory(Strict):
    """One story as the *editor* returns it: no article, that is stage 2."""

    cluster_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)

    @field_validator("title", "summary")
    @classmethod
    def _clean(cls, value: str) -> str:
        return _no_em_dash(value.strip())


class EditorSection(Strict):
    """One section as the editor returns it.

    Deliberately lenient about the two things the API's structured-output
    subset cannot enforce and the model therefore gets wrong: the section
    name, and the min-2 story budget (it rejects minItems above 1). Both are
    normalized deterministically in assemble.py, which drops sections that
    are unknown, empty, or short and moves their stories to briefly, exactly
    as SPEC 6.5 prescribes. The final Edition model still enforces the real
    constraints on the published artifact, so nothing is weakened: the
    leniency lives only in what the model is allowed to hand back.
    """

    name: str
    stories: list[EditorStory] = Field(max_length=MAX_STORIES_PER_SECTION)


class EditorResponse(Strict):
    """The edition core (SPEC 6.5 stage 1). No prose the writer owns.

    Slugs, scores, source URLs, stats and edition_number are all filled in
    afterwards by deterministic code, so the model is never asked for a
    value the code already knows. That keeps the call small and keeps
    structural facts out of the model's hands (rule zero).
    """

    headline_of_the_day: str = Field(min_length=1)
    key_points: list[KeyPoint] = Field(min_length=3, max_length=6)
    sections: list[EditorSection] = Field(min_length=1)
    briefly: list[str] = Field(default_factory=list)

    @field_validator("headline_of_the_day")
    @classmethod
    def _clean(cls, value: str) -> str:
        return _no_em_dash(value.strip())


class WriterResponse(Strict):
    """One article (SPEC 6.5 stage 2). Same shape as Article."""

    background: str = Field(min_length=1)
    what_happened: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    quote: Quote | None = None

    @field_validator("background", "what_happened", "why_it_matters")
    @classmethod
    def _clean(cls, value: str) -> str:
        return _no_em_dash(value.strip())


# The Anthropic structured-output (json_schema) format accepts only a subset
# of JSON Schema: it rejects value constraints like array minItems/maxItems
# above 1, string length bounds, numeric bounds, and pattern. Those are
# validation, not structure, and the pydantic models above are the real
# authority on a valid reply (rule zero), so they are stripped from the API
# schema and still enforced on every parsed response.
_API_STRIP_KEYS = frozenset(
    {
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "pattern",
        "format",
    }
)


def _api_schema(model: type[BaseModel]) -> dict:
    """A pydantic model as a flat JSON Schema the Anthropic API accepts.

    Inlines $defs, forces additionalProperties: false everywhere (which the
    API requires and pydantic does not emit by default for nested models),
    and drops the value-constraint keywords the API's structured-output
    subset does not support.
    """
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if ref and ref.startswith("#/$defs/"):
                return resolve(defs[ref.split("/")[-1]])
            out = {
                key: resolve(value)
                for key, value in node.items()
                if key not in _API_STRIP_KEYS
            }
            if out.get("type") == "object":
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


EDITOR_RESPONSE_SCHEMA = _api_schema(EditorResponse)
WRITER_RESPONSE_SCHEMA = _api_schema(WriterResponse)
