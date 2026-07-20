"""Clustering (SPEC 6.4b): local embeddings, greedy assignment.

Embeddings are local sentence-transformers vectors, so clustering costs
nothing per run (SPEC 9) and can re-run as often as it likes. That is what
makes the rebuild-the-partition strategy in run_silver.py affordable.

The math here takes embeddings as an argument rather than computing them,
so tests drive it with hand-built vectors and never load a model.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from ..adapters.base import RawItem

log = logging.getLogger(__name__)

CLUSTER_ID_CHARS = 32


def embed_text(item: RawItem, embed_chars: int) -> str:
    """The text that represents one item to the embedding model.

    Title plus a bounded slice of the body. Title alone is too sparse to
    separate near-duplicate wire copy; the whole 1200-char excerpt lets
    boilerplate (bylines, subscribe prompts) dominate the vector.
    """
    body = item.body_excerpt[:embed_chars].strip()
    return f"{item.title}\n{body}" if body else item.title


@lru_cache(maxsize=2)
def _load_model(model_name: str):
    """Load once per process. The model is ~90MB and reused every run."""
    from sentence_transformers import SentenceTransformer

    log.info("loading embedding model %s", model_name)
    return SentenceTransformer(model_name)


def embed(texts: list[str], model_name: str) -> np.ndarray:
    """Unit-normalized embeddings, so cosine similarity is a dot product."""
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    model = _load_model(model_name)
    vectors = model.encode(
        texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
    )
    return np.asarray(vectors, dtype=np.float32)


@dataclass
class Cluster:
    """One story: the items that appear to be reporting the same thing."""

    members: list[RawItem] = field(default_factory=list)
    _vectors: list[np.ndarray] = field(default_factory=list, repr=False)

    @property
    def seed(self) -> RawItem:
        """The earliest-published member. Defines the cluster's identity.

        Stable across rebuilds because bronze is append-only and the
        greedy pass walks items in published_at order, so the same item
        seeds the same cluster every time the day is re-clustered.
        """
        return self.members[0]

    @property
    def cluster_id(self) -> str:
        return hashlib.sha256(self.seed.item_id.encode()).hexdigest()[:CLUSTER_ID_CHARS]

    @property
    def centroid(self) -> np.ndarray:
        mean = np.mean(self._vectors, axis=0)
        norm = float(np.linalg.norm(mean))
        return mean / norm if norm else mean

    @property
    def canonical_urls(self) -> set[str]:
        return {member.canonical_url for member in self.members}

    def add(self, item: RawItem, vector: np.ndarray) -> None:
        self.members.append(item)
        self._vectors.append(vector)


def cluster(
    items: list[RawItem], embeddings: np.ndarray, threshold: float
) -> list[Cluster]:
    """Greedy clustering: join the best cluster above threshold, else open one.

    Items must arrive in published_at order (dedup.dedup returns them that
    way). That ordering is what makes cluster_id reproducible.
    """
    if not items:
        return []
    if len(items) != len(embeddings):
        raise ValueError(
            f"got {len(items)} items but {len(embeddings)} embeddings"
        )

    clusters: list[Cluster] = []
    for item, vector in zip(items, embeddings):
        # SPEC 6.4b: an identical canonical_url always merges, whatever
        # the cosine says. Same-day duplicates are normally gone by now
        # (dedup.dedup), so this fires on cross-day input.
        exact = next(
            (c for c in clusters if item.canonical_url in c.canonical_urls), None
        )
        if exact is not None:
            exact.add(item, vector)
            continue

        best: Cluster | None = None
        best_score = threshold
        for candidate in clusters:
            score = float(np.dot(vector, candidate.centroid))
            if score >= best_score:
                best, best_score = candidate, score

        if best is None:
            new = Cluster()
            new.add(item, vector)
            clusters.append(new)
        else:
            best.add(item, vector)

    log.info("clustered %d items into %d clusters", len(items), len(clusters))
    return clusters
