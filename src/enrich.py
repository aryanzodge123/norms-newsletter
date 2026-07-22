"""Article-text enrichment (SPEC 6.1, body_excerpt).

Adapters fill body_excerpt from the feed's summary, and feed summaries are
one-line blurbs. That left the writer stage with nothing to ground on, so
stories published as collapsed cards with no article (decision #16 forbids
writing specifics that are not in the grounding, correctly). This module
fetches the item's canonical_url and extracts the main article text so
body_excerpt is what SPEC 6.1 describes: the first ~1200 characters of the
item's body.

Runs in the collector, before the bronze write, so the text is stored once
and every later stage reads it: clustering embeds real text rather than a
title, scoring stops being headline-only (the M2 confidence finding), and
the writer stage has something to write from.

Two invariants:

- **Never fatal.** A timeout, an error status, a non-HTML page, an oversized
  body, or a parse failure all leave the item's original excerpt in place.
  This mirrors the collector's rule that one source failing never fails a run.
- **item_id is untouched.** It derives from canonical_url and published_at
  (adapters/base.py), never from the body, so enriching an item cannot
  disturb bronze dedup or produce a second row for the same story.

The fetched text is grounding input. It is stored in bronze and paraphrased
by the writer; it is never republished verbatim (decision #10), and the quote
policy (decision #15) is unchanged.
"""

from __future__ import annotations

import logging
import multiprocessing
import queue
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import httpx

from .adapters.base import USER_AGENT, RawItem, excerpt
from .config import EnrichConfig

log = logging.getLogger(__name__)

# Only these are worth parsing. A PDF, an image, or a video is a fetch we
# should not have made and certainly should not try to read as HTML.
HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")

# Fallback time budget for one isolated extraction when a caller does not pass
# its own (the pipeline passes enrich.extract_timeout_seconds). A crashing or
# hanging page costs at most this long before the regex fallback runs.
EXTRACT_TIMEOUT_DEFAULT = 8.0

# Fallback extraction: paragraph text, tags stripped. Proven adequate on the
# live sources (5,000 to 10,000 characters), and it keeps the module working
# if trafilatura is unavailable or returns nothing for a given page.
PARAGRAPH_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)


def _strip_paragraphs(html: str) -> str:
    """Main text from <p> blocks, scripts and styles removed first."""
    import html as html_module

    cleaned = SCRIPT_STYLE_RE.sub(" ", html)
    parts = []
    for block in PARAGRAPH_RE.findall(cleaned):
        text = html_module.unescape(TAG_RE.sub(" ", block))
        text = " ".join(text.split())
        if text:
            parts.append(text)
    return " ".join(parts)


def _trafilatura_extract(html: str) -> str:
    """The trafilatura call itself, whitespace normalized.

    Returns "" when trafilatura is unavailable, finds nothing it recognizes as
    an article, or raises. It does not fall back here: the caller decides. This
    runs both in-process (isolate=False) and inside the isolation worker.
    """
    try:
        import trafilatura

        text = trafilatura.extract(
            html, include_comments=False, include_tables=False, no_fallback=False
        )
        if text:
            return " ".join(text.split())
    except ImportError:
        log.debug("trafilatura not installed, using the paragraph fallback")
    except Exception as exc:  # noqa: BLE001 - a parse failure is not fatal
        log.debug("trafilatura failed, using the paragraph fallback: %s", exc)
    return ""


def _extract_worker(html: str, result_queue) -> None:
    """Run trafilatura in a child process, returning its text via the queue.

    A native segfault in trafilatura kills only this child, not the collector.
    Any failure yields "", which the parent reads as "use the fallback". If the
    child crashes before putting anything, the parent sees the process die and
    falls back instead.
    """
    try:
        result_queue.put(_trafilatura_extract(html))
    except Exception:  # noqa: BLE001 - the parent falls back on anything
        result_queue.put("")


def _run_isolated(worker, html: str, timeout: float) -> str | None:
    """Run `worker` in a spawned child and return the text it puts on the queue.

    Returns the child's result (possibly "") on a clean run, or None when the
    child crashed, was killed, or ran past the timeout. The worker is a
    parameter so the isolation mechanism can be tested with a crashing or
    hanging stand-in that does not depend on trafilatura.

    spawn is used rather than fork because enrich_items runs this from a thread
    pool, and forking a multithreaded parent is unsafe; spawn also behaves the
    same on macOS and on the Linux Actions runner.
    """
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()
    proc = ctx.Process(target=worker, args=(html, result_queue), daemon=True)
    proc.start()
    result: str | None = None
    deadline = time.monotonic() + timeout
    try:
        # Poll rather than one long blocking get: a crashed child never puts a
        # result, and get cannot tell the child died, so a plain get would wait
        # the whole timeout on every crash. Polling lets a dead child fall back
        # at once while a genuine hang still costs the full budget.
        while True:
            try:
                result = result_queue.get(timeout=0.1)
                break
            except queue.Empty:
                if not proc.is_alive():
                    # The child exited without a result: it crashed or was
                    # killed. One last non-blocking read in case it put a result
                    # and exited between our get and this check.
                    try:
                        result = result_queue.get_nowait()
                    except queue.Empty:
                        log.debug("isolated extraction process died, using the fallback")
                    break
                if time.monotonic() >= deadline:
                    log.debug("isolated extraction timed out, using the fallback")
                    break
    finally:
        if proc.is_alive():
            proc.terminate()
        proc.join(timeout=1.0)
        result_queue.close()
    return result


def extract_text(
    html: str, *, isolate: bool = True, timeout: float = EXTRACT_TIMEOUT_DEFAULT
) -> str:
    """The main article text of one page.

    trafilatura first, because it strips navigation, boilerplate, and comment
    sections rather than taking every paragraph on the page. The paragraph
    scrape is the fallback when trafilatura is unavailable, finds nothing it
    recognizes as an article, or crashes.

    trafilatura wraps native libraries that can segfault on some HTML, and a
    segfault cannot be caught in-process. With isolate=True the trafilatura call
    runs in a child process, so a crash becomes a failed result that the parent
    recovers from by running the regex fallback here. isolate=False runs it
    in-process, for tests and callers that have accepted the crash risk.
    """
    if not html or not html.strip():
        return ""
    text = _run_isolated(_extract_worker, html, timeout) if isolate else _trafilatura_extract(html)
    if text:
        return text
    return _strip_paragraphs(html)


def _host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def should_fetch(item: RawItem, config: EnrichConfig) -> bool:
    """Whether this item is worth a network round trip."""
    if not config.enabled:
        return False
    if len(item.body_excerpt.strip()) >= config.min_chars:
        return False  # already carries real text
    if not item.canonical_url.startswith(("http://", "https://")):
        return False
    return _host_of(item.canonical_url) not in set(config.skip_hosts)


def fetch_text(url: str, config: EnrichConfig, client: httpx.Client) -> str:
    """Fetch one page and return its article text, or "" on any problem."""
    try:
        response = client.get(
            url,
            timeout=config.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        if response.status_code != 200:
            log.debug("enrich: %s returned %s", url, response.status_code)
            return ""

        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type and not content_type.startswith(HTML_CONTENT_TYPES):
            log.debug("enrich: %s is %s, not HTML", url, content_type)
            return ""

        body = response.content
        if len(body) > config.max_bytes:
            log.debug("enrich: %s is %d bytes, over the cap", url, len(body))
            return ""

        return extract_text(
            response.text,
            isolate=config.isolate_extraction,
            timeout=config.extract_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - never fatal, per the module docstring
        log.debug("enrich: %s failed: %s", url, type(exc).__name__)
        return ""


def enrich_items(
    items: list[RawItem],
    config: EnrichConfig,
    *,
    client: httpx.Client | None = None,
) -> tuple[list[RawItem], dict]:
    """Fill thin body_excerpts by fetching the linked article.

    Returns the items (enriched where possible) and a metrics dict for the
    run log. Items are returned in their input order, and any item that was
    not fetched, or whose fetch did not improve on what it already had, is
    returned unchanged.
    """
    metrics = {"considered": len(items), "fetched": 0, "enriched": 0, "chars_added": 0}
    if not config.enabled or not items:
        return items, metrics

    targets = [(i, item) for i, item in enumerate(items) if should_fetch(item, config)]
    if not targets:
        return items, metrics

    owns_client = client is None
    client = client or httpx.Client(follow_redirects=True)
    enriched = list(items)
    try:
        with ThreadPoolExecutor(max_workers=config.max_concurrency) as pool:
            texts = list(
                pool.map(lambda pair: fetch_text(pair[1].canonical_url, config, client), targets)
            )

        for (index, item), text in zip(targets, texts):
            metrics["fetched"] += 1
            if not text:
                continue
            # SPEC 6.1's length rule lives in adapters.base.excerpt; call it
            # rather than truncating here, so there is one definition.
            trimmed = excerpt(text)
            before = len(item.body_excerpt.strip())
            if len(trimmed) <= before:
                continue  # the fetch did not beat what the feed already gave us
            enriched[index] = item.model_copy(update={"body_excerpt": trimmed})
            metrics["enriched"] += 1
            metrics["chars_added"] += len(trimmed) - before
    finally:
        if owns_client:
            client.close()

    log.info(
        "enrich: fetched %d of %d items, improved %d (+%d chars)",
        metrics["fetched"],
        metrics["considered"],
        metrics["enriched"],
        metrics["chars_added"],
    )
    return enriched, metrics
