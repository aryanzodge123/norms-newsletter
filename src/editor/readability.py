"""The readability gate (SPEC 6.5, decision #14).

Flesch-Kincaid grade level over all generated text. The edition average
must be grade 9 or below to publish. Over the line: one automatic revision
pass with the failing sentences listed, then publish anyway and flag it in
the run log. Availability beats perfection, but the flag is reviewed
(SPEC section 8's weekly review).

Implemented here rather than pulled from a dependency on purpose. The
syllable heuristic is the whole gate: if it shifts under a version bump,
the grade shifts with it and the publish/flag decision changes without
anyone touching the pipeline. Pinned in code, pinned by tests.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# Decision #14 and voice standard 1.
MAX_GRADE = 9.0

# Which sentences the revision pass is told about. A sentence a little over
# the edition target is not the problem; the ones well past it are.
SENTENCE_FLAG_GRADE = 12.0

# Flesch-Kincaid grade level coefficients. Frozen: these are the formula.
_FK_WORDS_PER_SENTENCE = 0.39
_FK_SYLLABLES_PER_WORD = 11.8
_FK_CONSTANT = 15.59

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])[\s ]+")
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_VOWEL_GROUP = re.compile(r"[aeiouy]+")


def split_sentences(text: str) -> list[str]:
    """Sentences, for the per-sentence report and the word/sentence ratio."""
    parts = (part.strip() for part in _SENTENCE_SPLIT.split(text or ""))
    return [part for part in parts if _WORD.search(part)]


def words(text: str) -> list[str]:
    """Words as the formula counts them: alphabetic tokens only.

    Numerals are excluded deliberately. "2026" has no defensible syllable
    count, and including it as a one-syllable word makes number-heavy
    finance copy read as easier than it is.
    """
    return _WORD.findall(text or "")


def count_syllables(word: str) -> int:
    """Syllables in one word, by the standard vowel-group heuristic.

    Approximate by nature. It is wrong on some words in both directions and
    that is tolerable: the gate is a trend check over a whole edition, not
    a per-word oracle. What matters is that it is *stable*, so the same
    text always scores the same.
    """
    cleaned = re.sub(r"[^a-z]", "", word.casefold())
    if not cleaned:
        return 0

    groups = _VOWEL_GROUP.findall(cleaned)
    count = len(groups)

    # Silent trailing e: "make" is one syllable, not two. The "le" and "ee"
    # exclusions keep the syllable that is really there in "table" and
    # "agree", and count > 1 keeps "the" and "be" from reaching zero.
    if cleaned.endswith("e") and not cleaned.endswith(("le", "ee")) and count > 1:
        count -= 1

    return max(count, 1)


def grade(text: str) -> float:
    """Flesch-Kincaid grade level for a passage.

    Returns 0.0 for text with no words, which keeps empty or absent
    sections from dragging an edition average toward zero and passing a
    gate they never took.
    """
    sentences = split_sentences(text)
    tokens = words(text)
    if not sentences or not tokens:
        return 0.0

    syllables = sum(count_syllables(word) for word in tokens)
    return (
        _FK_WORDS_PER_SENTENCE * (len(tokens) / len(sentences))
        + _FK_SYLLABLES_PER_WORD * (syllables / len(tokens))
        - _FK_CONSTANT
    )


def failing_sentences(text: str, threshold: float = SENTENCE_FLAG_GRADE) -> list[str]:
    """The sentences worth rewriting, hardest first.

    This is what the revision pass is handed. Telling a model "this is too
    hard to read" achieves little; telling it which sentences, in order,
    gives it something to act on.
    """
    scored = [(grade(sentence), sentence) for sentence in split_sentences(text)]
    return [
        sentence
        for score, sentence in sorted(scored, key=lambda pair: -pair[0])
        if score > threshold
    ]


def story_text(story: dict) -> str:
    """Every word of one story that the pipeline generated.

    The summary counts even when the article does not exist, because a
    collapsed card is still published prose.
    """
    parts = [story.get("summary") or ""]
    article = story.get("article")
    if article:
        parts.extend(
            article.get(key) or ""
            for key in ("background", "what_happened", "why_it_matters")
        )
        quote = article.get("quote")
        if quote:
            # A quote is a person's own words. It is published, so it is
            # measured, but it is never rewritten: see revisable_text.
            parts.append(quote.get("text") or "")
    return " ".join(part for part in parts if part)


def revisable_text(story: dict) -> str:
    """The part of a story a revision pass is allowed to change.

    Everything in story_text except the quote. Rewriting a quotation to
    lower its reading grade would put words in a real person's mouth,
    which decision #15 exists to prevent.
    """
    parts = [story.get("summary") or ""]
    article = story.get("article")
    if article:
        parts.extend(
            article.get(key) or ""
            for key in ("background", "what_happened", "why_it_matters")
        )
    return " ".join(part for part in parts if part)


def edition_text(edition: dict) -> str:
    """All generated text in an edition (voice standard preamble).

    Glance points, summaries, articles and briefly lines. Source titles
    are excluded: they are other outlets' words, quoted structurally, and
    the pipeline cannot rewrite them.
    """
    parts = [edition.get("headline_of_the_day") or ""]
    parts.extend(point.get("text") or "" for point in edition.get("key_points") or [])
    for section in edition.get("sections") or []:
        for story in section.get("stories") or []:
            parts.append(story_text(story))
    if edition.get("edition_type") == "fallback":
        parts.append(edition.get("notice") or "")
    return " ".join(part for part in parts if part)


class Report:
    """The gate's verdict on one edition."""

    def __init__(self, average: float, per_story: dict[str, float]):
        self.average = average
        self.per_story = per_story

    @property
    def passes(self) -> bool:
        return self.average <= MAX_GRADE

    @property
    def failing_slugs(self) -> list[str]:
        """Stories to re-call in the revision pass, hardest first.

        Only stories that are themselves over the line. An edition can fail
        on its average while most stories are fine, and rewriting the ones
        that are fine costs money and risks making them worse.
        """
        return [
            slug
            for slug, score in sorted(self.per_story.items(), key=lambda p: -p[1])
            if score > MAX_GRADE
        ]

    def __repr__(self) -> str:
        return f"Report(average={self.average:.2f}, passes={self.passes})"


def assess(edition: dict) -> Report:
    """Grade an edition. Returns the report; decides nothing.

    The publish/revise/flag decision belongs to the runner (SPEC 6.5), so
    this stays a pure function over a dict and is trivially testable.
    """
    per_story = {
        story["slug"]: grade(story_text(story))
        for section in edition.get("sections") or []
        for story in section.get("stories") or []
    }
    average = grade(edition_text(edition))
    log.info(
        "readability: edition average grade %.2f (limit %.1f), %d of %d stories over",
        average,
        MAX_GRADE,
        len([s for s in per_story.values() if s > MAX_GRADE]),
        len(per_story),
    )
    return Report(average=average, per_story=per_story)
