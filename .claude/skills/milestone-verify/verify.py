#!/usr/bin/env python3
"""Milestone verification gate for Norm's Newsletter.

Three deterministic checks, per CLAUDE.md milestone workflow:

  1. tests     run the pytest suite over the deterministic layers
  2. fixtures  validate site/fixtures/*.json against the edition schema
  3. urls      prove every absolute self-URL derives from astro.config

A check that cannot run yet (the milestone that builds it has not landed)
reports SKIP and does not fail the gate. Only FAIL is fatal.

Exit code 0 means the gate passed.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SITE = REPO / "site"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))


# --------------------------------------------------------------------------
# 1. Test suite
# --------------------------------------------------------------------------
def check_tests() -> None:
    tests_dir = REPO / "tests"
    if not tests_dir.is_dir() or not any(tests_dir.glob("test_*.py")):
        record("tests", SKIP, "no tests/test_*.py yet")
        return

    proc = subprocess.run(
        ["uv", "run", "pytest", "-q"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    summary = tail[-1] if tail else "no output"
    if proc.returncode == 0:
        record("tests", PASS, summary)
    else:
        record("tests", FAIL, summary)
        print("\n--- pytest output ---")
        print(proc.stdout)
        print(proc.stderr)


# --------------------------------------------------------------------------
# 2. Fixtures validate against the edition schema (SPEC 6.5)
# --------------------------------------------------------------------------
def load_validator():
    """Return a callable(dict) that raises on an invalid edition, or None.

    src/editor/schema.py is expected to expose either a `validate_edition`
    callable or an `EDITION_SCHEMA` JSON Schema dict.
    """
    schema_path = REPO / "src" / "editor" / "schema.py"
    if not schema_path.exists():
        return None, "src/editor/schema.py does not exist yet (built in M3)"

    sys.path.insert(0, str(REPO / "src"))
    try:
        from editor import schema as editor_schema  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return None, f"could not import editor.schema: {exc}"

    if callable(getattr(editor_schema, "validate_edition", None)):
        return editor_schema.validate_edition, ""

    raw = getattr(editor_schema, "EDITION_SCHEMA", None)
    if isinstance(raw, dict):
        try:
            import jsonschema
        except ImportError:
            return None, "EDITION_SCHEMA found but jsonschema is not installed"
        return (lambda obj: jsonschema.validate(obj, raw)), ""

    return None, "editor.schema exposes neither validate_edition nor EDITION_SCHEMA"


def check_fixtures() -> None:
    fixtures_dir = SITE / "fixtures"
    fixtures = sorted(fixtures_dir.glob("*.json")) if fixtures_dir.is_dir() else []
    if not fixtures:
        record("fixtures", SKIP, "site/fixtures/*.json does not exist yet (built in M3)")
        return

    validate, why = load_validator()
    if validate is None:
        record("fixtures", SKIP, why)
        return

    expected = {"normal.json", "quiet.json", "fallback.json"}
    found = {f.name for f in fixtures}
    failures: list[str] = []

    for missing in sorted(expected - found):
        failures.append(f"{missing}: required fixture missing (DESIGN.md section 5)")

    for fixture in fixtures:
        try:
            validate(json.loads(fixture.read_text()))
        except Exception as exc:  # noqa: BLE001
            first_line = str(exc).strip().splitlines()[0]
            failures.append(f"{fixture.name}: {first_line}")

    if failures:
        record("fixtures", FAIL, f"{len(failures)} problem(s)")
        for line in failures:
            print(f"    {line}")
    else:
        record("fixtures", PASS, f"{len(fixtures)} fixture(s) valid")


# --------------------------------------------------------------------------
# 3. No hardcoded URLs (SPEC 6.6)
# --------------------------------------------------------------------------
CONFIG_RE = {
    "site": re.compile(r"""\bsite\s*:\s*['"]([^'"]+)['"]"""),
    "base": re.compile(r"""\bbase\s*:\s*['"]([^'"]+)['"]"""),
}
URL_RE = re.compile(r"""https?://[^\s'"<>)\]]+""")
SOURCE_SUFFIXES = {".astro", ".ts", ".js", ".mjs", ".jsx", ".tsx", ".md", ".css"}


def read_astro_config() -> tuple[str | None, str | None]:
    config = SITE / "astro.config.mjs"
    if not config.exists():
        return None, None
    text = config.read_text()
    site = CONFIG_RE["site"].search(text)
    base = CONFIG_RE["base"].search(text)
    return (site.group(1) if site else None, base.group(1) if base else None)


def is_self_host(url: str, site_url: str | None) -> bool:
    """True if the URL points at our own site rather than an external source."""
    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    if host.endswith("github.io"):
        return True
    if site_url:
        return host == site_url.split("//", 1)[-1].split("/", 1)[0].lower()
    return False


def check_urls() -> None:
    if not SITE.is_dir():
        record("urls", SKIP, "site/ does not exist yet")
        return

    site_url, base = read_astro_config()
    failures: list[str] = []

    if site_url is None or base is None:
        record(
            "urls",
            SKIP,
            "astro.config.mjs does not define site and base yet (set in M4)",
        )
    else:
        expected_prefix = site_url.rstrip("/") + "/" + base.strip("/")
        expected_prefix = expected_prefix.rstrip("/")

        # a) Source files must never contain a self-referential absolute URL.
        src_root = SITE / "src"
        for path in sorted(src_root.rglob("*")) if src_root.is_dir() else []:
            if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
                continue
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                for url in URL_RE.findall(line):
                    if is_self_host(url, site_url):
                        rel = path.relative_to(REPO)
                        failures.append(
                            f"{rel}:{lineno}: hardcoded self URL {url} "
                            "(derive it from astro.config instead)"
                        )

        # b) Build output: every self-URL must match the configured prefix.
        dist = SITE / "dist"
        if not dist.is_dir():
            print("    note: site/dist not found, source-only URL check")
        else:
            seen: set[str] = set()
            for path in dist.rglob("*"):
                if not path.is_file() or path.suffix not in {
                    ".html", ".xml", ".json", ".js", ".css", ".txt",
                }:
                    continue
                for url in URL_RE.findall(path.read_text(errors="ignore")):
                    if is_self_host(url, site_url) and not url.startswith(
                        expected_prefix
                    ):
                        seen.add(f"{path.relative_to(REPO)}: {url}")
            failures.extend(sorted(seen))

        if failures:
            record("urls", FAIL, f"{len(failures)} hardcoded URL(s)")
            for line in failures[:25]:
                print(f"    {line}")
            if len(failures) > 25:
                print(f"    ... and {len(failures) - 25} more")
        else:
            record("urls", PASS, f"all self URLs derive from {expected_prefix}")


# --------------------------------------------------------------------------
def main() -> int:
    print("milestone-verify\n")
    check_tests()
    check_fixtures()
    check_urls()

    print()
    for name, status, detail in results:
        print(f"  [{status}] {name:9} {detail}")

    failed = [r for r in results if r[1] == FAIL]
    skipped = [r for r in results if r[1] == SKIP]
    print()
    if failed:
        print(f"GATE FAILED: {', '.join(r[0] for r in failed)}")
        return 1
    if skipped:
        print(f"GATE PASSED (skipped: {', '.join(r[0] for r in skipped)})")
    else:
        print("GATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
