"""Clustering math (SPEC 6.4b).

Every test here drives cluster() with hand-built unit vectors. No model is
loaded and no network is touched: the threshold behavior is arithmetic,
and testing it against real embeddings would be testing sentence
transformers, not this code.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
import pytest

from src.silver.cluster import Cluster, cluster, embed_text
from tests.conftest import make_item

THRESHOLD = 0.82


def unit(*values: float) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def at_angle(degrees: float) -> np.ndarray:
    """A 2-D unit vector this many degrees off the x axis.

    cos(30 degrees) is about 0.866, above the 0.82 threshold.
    cos(45 degrees) is about 0.707, below it.
    """
    radians = math.radians(degrees)
    return np.array([math.cos(radians), math.sin(radians)], dtype=np.float32)


def items(n: int, *, minutes_apart: int = 10):
    base = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
    return [
        make_item(
            f"https://example.com/{i}",
            title=f"Story {i}",
            source=f"source{i}",
            published_at=base.replace(minute=i * minutes_apart % 60),
        )
        for i in range(n)
    ]


class TestThreshold:
    def test_similar_items_merge(self) -> None:
        pair = items(2)
        vectors = np.stack([at_angle(0), at_angle(30)])
        result = cluster(pair, vectors, THRESHOLD)
        assert len(result) == 1
        assert len(result[0].members) == 2

    def test_dissimilar_items_stay_apart(self) -> None:
        pair = items(2)
        vectors = np.stack([at_angle(0), at_angle(45)])
        result = cluster(pair, vectors, THRESHOLD)
        assert len(result) == 2

    def test_exactly_at_threshold_merges(self) -> None:
        """`cosine >= threshold` per SPEC 6.4b, not strictly greater.

        Tested at cosine 1.0 with identical vectors rather than at 0.82,
        because 0.82 has no exact float32 representation: a vector built
        to sit on that boundary lands a fraction under it after
        normalization, and the test would be measuring float precision
        instead of the comparison. At 1.0 the dot product is exact, so a
        `>` here would fail and a `>=` passes.
        """
        pair = items(2)
        same = np.array([1.0, 0.0], dtype=np.float32)
        result = cluster(pair, np.stack([same, same]), 1.0)
        assert len(result) == 1

    def test_just_below_threshold_does_not_merge(self) -> None:
        pair = items(2)
        below = THRESHOLD - 0.01
        vectors = np.stack(
            [
                np.array([1.0, 0.0], dtype=np.float32),
                np.array([below, math.sqrt(1 - below**2)], dtype=np.float32),
            ]
        )
        assert len(cluster(pair, vectors, THRESHOLD)) == 2

    def test_joins_the_best_cluster_not_the_first_acceptable_one(self) -> None:
        """SPEC 6.4b says join the best cluster, so a walk that stopped at
        the first match above threshold would be wrong."""
        # 0 and 40 degrees are too far apart to merge, so they open two
        # clusters. The third item at 25 degrees is above threshold
        # against both, and must take the nearer one.
        assert math.cos(math.radians(40)) < THRESHOLD
        assert math.cos(math.radians(25)) > THRESHOLD  # matches the first
        assert math.cos(math.radians(15)) > THRESHOLD  # matches the second, closer

        three = items(3)
        vectors = np.stack([at_angle(0), at_angle(40), at_angle(25)])
        result = cluster(three, vectors, THRESHOLD)

        assert sorted(len(c.members) for c in result) == [1, 2]
        merged = next(c for c in result if len(c.members) == 2)
        assert merged.seed.item_id == three[1].item_id, "took the nearer cluster"


class TestCanonicalUrlOverride:
    def test_identical_canonical_url_always_merges(self) -> None:
        """SPEC 6.4b: identical canonical_url merges whatever the cosine says."""
        base = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
        pair = [
            make_item("https://example.com/a", published_at=base),
            make_item(
                "https://example.com/a",
                published_at=base.replace(hour=10),
                title="Different headline entirely",
            ),
        ]
        assert pair[0].canonical_url == pair[1].canonical_url
        # Orthogonal vectors: cosine 0, far below any threshold.
        vectors = np.stack([unit(1, 0), unit(0, 1)])
        result = cluster(pair, vectors, THRESHOLD)
        assert len(result) == 1


class TestClusterIdentity:
    def test_cluster_id_is_stable_across_rebuilds(self) -> None:
        """The property the partition rebuild depends on."""
        three = items(3)
        vectors = np.stack([at_angle(0), at_angle(90), at_angle(180)])
        first = cluster(three, vectors, THRESHOLD)
        second = cluster(three, vectors, THRESHOLD)
        assert [c.cluster_id for c in first] == [c.cluster_id for c in second]

    def test_cluster_id_survives_a_new_member_arriving(self) -> None:
        """A cluster that grows keeps its id, so its score can carry forward."""
        three = items(3)
        before = cluster(three[:2], np.stack([at_angle(0), at_angle(30)]), THRESHOLD)
        after = cluster(
            three, np.stack([at_angle(0), at_angle(30), at_angle(20)]), THRESHOLD
        )
        assert len(before) == 1 and len(after) == 1
        assert before[0].cluster_id == after[0].cluster_id
        assert len(after[0].members) == 3

    def test_a_late_earlier_published_item_reseeds(self) -> None:
        """The documented edge case: costs one extra scoring call, no more."""
        base = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
        original = make_item("https://example.com/a", published_at=base)
        late_arrival = make_item(
            "https://example.com/b", published_at=base.replace(hour=8)
        )

        before = cluster([original], np.stack([at_angle(0)]), THRESHOLD)
        after = cluster(
            [late_arrival, original], np.stack([at_angle(0), at_angle(10)]), THRESHOLD
        )
        assert before[0].cluster_id != after[0].cluster_id
        assert after[0].seed.item_id == late_arrival.item_id

    def test_cluster_id_is_32_hex_chars(self) -> None:
        result = cluster(items(1), np.stack([at_angle(0)]), THRESHOLD)
        assert len(result[0].cluster_id) == 32
        assert all(ch in "0123456789abcdef" for ch in result[0].cluster_id)


class TestCentroid:
    def test_centroid_is_the_normalized_mean(self) -> None:
        c = Cluster()
        pair = items(2)
        c.add(pair[0], unit(1, 0))
        c.add(pair[1], unit(0, 1))
        assert np.allclose(c.centroid, unit(1, 1), atol=1e-6)
        assert math.isclose(float(np.linalg.norm(c.centroid)), 1.0, abs_tol=1e-6)

    def test_matching_is_against_the_centroid_not_the_seed(self) -> None:
        """A cluster drifts toward its members, so late items match the
        story as it now reads rather than only its first headline."""
        threshold = 0.9
        # 0 and 20 degrees merge, putting the centroid at 10. The third
        # item at 33 degrees is too far from the seed to join it directly
        # but close enough to the centroid.
        assert math.cos(math.radians(33)) < threshold
        assert math.cos(math.radians(23)) > threshold

        three = items(3)
        vectors = np.stack([at_angle(0), at_angle(20), at_angle(33)])
        result = cluster(three, vectors, threshold)
        assert len(result) == 1
        assert len(result[0].members) == 3


class TestGuards:
    def test_empty_input(self) -> None:
        assert cluster([], np.zeros((0, 2)), THRESHOLD) == []

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="2 items but 1 embeddings"):
            cluster(items(2), np.stack([at_angle(0)]), THRESHOLD)


class TestEmbedText:
    def test_combines_title_and_bounded_body(self) -> None:
        item = make_item("https://example.com/a", title="Headline", body="x" * 900)
        text = embed_text(item, 500)
        assert text.startswith("Headline\n")
        assert len(text) == len("Headline\n") + 500

    def test_title_only_when_body_is_empty(self) -> None:
        item = make_item("https://example.com/a", title="Headline", body="   ")
        assert embed_text(item, 500) == "Headline"
