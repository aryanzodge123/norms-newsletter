"""Adapter contract and the shared normalization primitives (SPEC 6.1).

item_id is sha256(canonical_url + published_at)[:32], so bronze dedup is
only as reliable as the functions here are deterministic. The cleanup
rules in clean_url are frozen per spec version: changing them changes
every item_id and breaks dedup against existing bronze rows.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Iterable, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict

# Frozen per spec version (SPEC 6.1). Do not edit without a version bump
# and a documented bronze migration.
TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = frozenset(
    {"fbclid", "gclid", "msclkid", "igshid", "mc_cid", "mc_eid"}
)

REDIRECT_TIMEOUT_SECONDS = 3.0
REDIRECT_MAX_HOPS = 5

# The exact string form of published_at that feeds the item_id hash.
# Fixed here so the same instant always hashes identically regardless of
# the tzinfo an adapter happens to attach.
ITEM_ID_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

BODY_EXCERPT_CHARS = 1200

# One identifying User-Agent for every outbound request the pipeline makes,
# feeds and article fetches alike. Publishers are entitled to know who is
# calling, and several (CNBC among them) reject the default client string
# outright.
USER_AGENT = (
    "Mozilla/5.0 (compatible; NormsNewsletter/1.0; "
    "+https://aryanzodge123.github.io/norms-newsletter/)"
)


class RawItem(BaseModel):
    """One normalized item, matching the bronze schema in SPEC 6.1."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    source: str
    source_type: str
    topic_hint: str
    url: str
    canonical_url: str
    title: str
    body_excerpt: str
    author: str | None
    published_at: datetime
    fetched_at: datetime
    run_id: str
    ingest_date: date  # partition column


class Adapter(Protocol):
    """One source. Fetches, normalizes, and returns rows (SPEC 6.1)."""

    name: str
    topic_hint: str

    def fetch(self, since: datetime) -> list[RawItem]: ...


def _is_tracking_param(key: str) -> bool:
    lowered = key.lower()
    return lowered in TRACKING_PARAMS or any(
        lowered.startswith(prefix) for prefix in TRACKING_PREFIXES
    )


def clean_url(url: str) -> str:
    """Deterministic cleanup, no network (SPEC 6.1). Frozen per version.

    Lowercases scheme and host, strips utm_* and known click IDs, drops
    the fragment, and removes a trailing slash from the path.
    """
    parts = urlsplit(url.strip())

    scheme = parts.scheme.lower()
    host = parts.hostname.lower() if parts.hostname else ""
    netloc = host
    if parts.port:
        netloc = f"{host}:{parts.port}"
    if parts.username:
        credentials = parts.username
        if parts.password:
            credentials += f":{parts.password}"
        netloc = f"{credentials}@{netloc}"

    path = parts.path
    if path.endswith("/") and len(path) > 1:
        path = path[:-1]
    elif path == "/":
        path = ""

    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_param(key)
    ]
    query = urlencode(kept)

    return urlunsplit((scheme, netloc, path, query, ""))


def _host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def resolve_redirects(
    url: str,
    *,
    timeout: float = REDIRECT_TIMEOUT_SECONDS,
    max_hops: int = REDIRECT_MAX_HOPS,
    client: httpx.Client | None = None,
) -> str:
    """Follow redirects for one URL. Returns the input on any failure."""
    owns_client = client is None
    client = client or httpx.Client(follow_redirects=False, timeout=timeout)
    current = url
    try:
        for _ in range(max_hops):
            response = client.head(current)
            if response.status_code not in (301, 302, 303, 307, 308):
                return current
            location = response.headers.get("location")
            if not location:
                return current
            current = str(httpx.URL(current).join(location))
        return url  # hop limit hit, fall back to the input
    except Exception:
        return url
    finally:
        if owns_client:
            client.close()


def canonicalize(
    url: str,
    shortener_hosts: Iterable[str] = (),
    *,
    client: httpx.Client | None = None,
) -> str:
    """Produce the canonical_url for an item (SPEC 6.1).

    Deterministic cleanup always. A network round trip only when the host
    is a configured shortener; on any failure the cleaned input is used.
    """
    cleaned = clean_url(url)
    hosts = {h.lower() for h in shortener_hosts}
    if hosts and _host_of(cleaned) in hosts:
        resolved = resolve_redirects(cleaned, client=client)
        if resolved != cleaned:
            return clean_url(resolved)
    return cleaned


def make_item_id(canonical_url: str, published_at: datetime) -> str:
    """sha256(canonical_url + published_at)[:32] (SPEC 6.1)."""
    if published_at.tzinfo is None:
        stamped = published_at.replace(tzinfo=UTC)
    else:
        stamped = published_at.astimezone(UTC)
    payload = canonical_url + stamped.strftime(ITEM_ID_TIME_FORMAT)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def excerpt(text: str | None) -> str:
    """First ~1200 chars of body text (SPEC 6.1)."""
    if not text:
        return ""
    collapsed = " ".join(text.split())
    return collapsed[:BODY_EXCERPT_CHARS]


def build_item(
    *,
    source: str,
    source_type: str,
    topic_hint: str,
    url: str,
    title: str,
    body: str | None,
    author: str | None,
    published_at: datetime,
    run_id: str,
    shortener_hosts: Iterable[str] = (),
    fetched_at: datetime | None = None,
    client: httpx.Client | None = None,
) -> RawItem:
    """Assemble a RawItem, deriving canonical_url, item_id, and partitions.

    Adapters call this rather than constructing RawItem directly, so the
    dedup-critical derivations happen in exactly one place.
    """
    fetched_at = fetched_at or datetime.now(UTC)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)

    canonical_url = canonicalize(url, shortener_hosts, client=client)
    return RawItem(
        item_id=make_item_id(canonical_url, published_at),
        source=source,
        source_type=source_type,
        topic_hint=topic_hint,
        url=url,
        canonical_url=canonical_url,
        title=" ".join(title.split()),
        body_excerpt=excerpt(body),
        author=author or None,
        published_at=published_at.astimezone(UTC),
        fetched_at=fetched_at,
        run_id=run_id,
        ingest_date=fetched_at.astimezone(UTC).date(),
    )
