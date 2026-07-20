"""canonical_url normalization (SPEC 6.1).

These rules are frozen per spec version. If a test here needs changing,
that is a spec change and a bronze migration, not a test fix.
"""

from __future__ import annotations

import httpx
import pytest

from src.adapters.base import canonicalize, clean_url, resolve_redirects


@pytest.mark.parametrize(
    "raw, expected",
    [
        # utm_* stripped, whatever the suffix
        (
            "https://example.com/a?utm_source=rss&utm_medium=feed&utm_content=x",
            "https://example.com/a",
        ),
        # known click IDs stripped
        ("https://example.com/a?fbclid=abc", "https://example.com/a"),
        ("https://example.com/a?gclid=abc", "https://example.com/a"),
        ("https://example.com/a?msclkid=abc", "https://example.com/a"),
        ("https://example.com/a?igshid=abc", "https://example.com/a"),
        ("https://example.com/a?mc_cid=abc&mc_eid=def", "https://example.com/a"),
        # meaningful params survive
        ("https://example.com/a?id=42", "https://example.com/a?id=42"),
        (
            "https://example.com/a?id=42&utm_source=rss",
            "https://example.com/a?id=42",
        ),
        # scheme and host lowercased, path case preserved
        ("HTTPS://Example.COM/Path", "https://example.com/Path"),
        # fragment dropped
        ("https://example.com/a#comments", "https://example.com/a"),
        # trailing slash removed, including the bare root
        ("https://example.com/a/", "https://example.com/a"),
        ("https://example.com/", "https://example.com"),
        # everything at once
        (
            "HTTPS://Example.com/Story/?utm_source=rss&id=7&fbclid=z#top",
            "https://example.com/Story?id=7",
        ),
    ],
)
def test_clean_url(raw: str, expected: str) -> None:
    assert clean_url(raw) == expected


def test_clean_url_is_idempotent() -> None:
    """Applying cleanup twice must not move the result, or item_ids drift."""
    messy = "HTTPS://Example.com/Story/?utm_source=rss&id=7#top"
    once = clean_url(messy)
    assert clean_url(once) == once


def test_clean_url_preserves_port() -> None:
    assert clean_url("http://Example.com:8080/a/") == "http://example.com:8080/a"


def test_canonicalize_makes_no_request_for_unlisted_hosts() -> None:
    """A host not in shortener_hosts is never resolved over the network."""

    def explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected network call to {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(explode))
    assert (
        canonicalize("https://example.com/a?utm_source=x", ("t.co",), client=client)
        == "https://example.com/a"
    )


def test_canonicalize_resolves_listed_shortener() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "t.co":
            return httpx.Response(
                301,
                headers={"location": "https://example.com/real/?utm_source=twitter"},
            )
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    # the resolved target is then run back through the deterministic cleanup
    assert (
        canonicalize("https://t.co/abc", ("t.co",), client=client)
        == "https://example.com/real"
    )


def test_canonicalize_falls_back_when_resolution_fails() -> None:
    """Timeouts and errors fall back to the cleaned input (SPEC 6.1)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("too slow")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert canonicalize("https://t.co/abc/", ("t.co",), client=client) == "https://t.co/abc"


def test_resolve_redirects_gives_up_after_hop_limit() -> None:
    """A redirect loop falls back to the input rather than spinning."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://t.co/loop"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert resolve_redirects("https://t.co/loop", client=client) == "https://t.co/loop"


def test_shortener_matching_is_case_insensitive() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "t.co":
            return httpx.Response(301, headers={"location": "https://example.com/real"})
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert (
        canonicalize("https://T.CO/abc", ("t.co",), client=client)
        == "https://example.com/real"
    )
