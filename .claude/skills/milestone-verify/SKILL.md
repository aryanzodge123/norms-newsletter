---
name: milestone-verify
description: Run the milestone verification gate for Norm's Newsletter. Runs the pytest suite, validates site/fixtures/*.json against the edition.json schema, and greps the site source and build output for hardcoded URLs. Use at the end of every milestone before writing the MILESTONES.md entry, and any time you need to confirm the repo is still in a publishable state.
---

# milestone-verify

The verification gate named in CLAUDE.md step 3 of the milestone workflow.
Run it before you write a MILESTONES.md entry, and before telling Milind a
milestone is ready to review.

## Run it

```bash
uv run python .claude/skills/milestone-verify/verify.py
```

Exit code 0 means the gate passed.

## What it checks

**1. tests** runs `uv run pytest -q`. These cover the deterministic layers
only: adapters, dedup, clustering math, edition schema validation, the
readability gate, and the DST scheduling check (CLAUDE.md rule 4). AI
calls are not under test; their schema validators are.

**2. fixtures** loads every `site/fixtures/*.json` and validates it against
the canonical edition schema in `src/editor/schema.py` (SPEC.md 6.5). It
also asserts that all three edition types exist as fixtures: `normal.json`,
`quiet.json`, `fallback.json` (DESIGN.md section 5). This is what keeps the
promise that the site develops without the live pipeline.

The schema module must expose one of:
- `validate_edition(obj)`, a callable that raises on an invalid edition, or
- `EDITION_SCHEMA`, a JSON Schema dict (requires `jsonschema` installed).

**3. urls** enforces the SPEC 6.6 rule that every absolute URL derives from
`astro.config`. It reads `site` and `base` from `site/astro.config.mjs`,
then:
- fails if any file under `site/src/` contains a self-referential absolute
  URL literal, and
- fails if any absolute self-URL in `site/dist/` does not start with the
  configured `site` + `base` prefix.

External URLs (source article links, the R2 audio host) are ignored by
design. Only URLs pointing at our own site are policed.

For the dist half to mean anything, build first:

```bash
cd site && npm run build
```

## Reading the output

- `FAIL` is fatal. Fix it before logging the milestone.
- `SKIP` means the milestone that builds that layer has not landed yet.
  Fixtures skip until M3, the dist URL check is source-only until M4.
  Skips are printed in the summary line so they never pass silently.

If a check skips at a milestone where it should be running, that is a real
problem. Fixtures skipping after M3, or urls skipping after M4, means
something was not wired up.

## Scope

This gate does not review design fidelity, prompt quality, or voice. Those
are judgment calls against DESIGN.md and belong in the milestone review
conversation, not in a script.
