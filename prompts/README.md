# `prompts/` - the AI prompts

These are the instructions given to the AI at each of the four places the
pipeline calls a model. They are plain Markdown so they can be read, reviewed,
and versioned like any other file.

Remember rule zero: the prompt is **not** the authority on what a valid response
looks like. The pydantic schema in code is (written before the prompt). The
prompt asks the model to produce good, on-policy content; the validator rejects
anything that does not conform.

## The files

| File | Used by | Purpose |
|------|---------|---------|
| `voice.md` | **every** stage | The writing voice standard, included at the top of every prompt |
| `scoring_v1.md` | `src/silver/score.py` | Rate a story cluster 1-10, assign a topic, one-sentence reason |
| `editor_v1.md` | `src/editor/run_editor.py` | Curate the edition: choose/order stories, write the headline, glance, summaries |
| `writer_v1.md` | `src/editor/run_writers.py` | Write one story's article (Background / What happened / Why it matters + optional quote) |
| `simplify_v1.md` | `src/editor/simplify.py` | Rewrite lines that read too hard, without changing the facts |
| `audio_script_v1.md` | `src/audio/script.py` | Turn the edition into a two-host spoken dialogue |

## The voice standard is shared and canonical

`voice.md` is DESIGN.md section 8, copied verbatim. **DESIGN.md is the source of
truth**; if the two ever differ, DESIGN.md wins and `voice.md` is the bug. Every
stage prepends it, so the whole pipeline writes in one consistent plain-English
voice. The code loads a prompt as `voice.md` + `---` + the stage file.

Key voice rules (all enforced downstream, not just requested):

- Write for a smart friend outside the industry, ~8th-grade reading level. The
  edition average must be grade 9 or below to publish (enforced by
  `src/editor/readability.py`).
- Explain every acronym or term on first use. Short sentences, one idea each.
- Neutral and calm: no hype words, no fear words, no political editorializing.
- **Never use an em dash.** Use periods, commas, or restructure. This is enforced
  in the schema validators, so a slipped em dash fails validation.
- Quotes: only a real person speaking, at most one per story, short, always
  attributed and linked (also enforced in the schema).

## The `_v1` naming

The version suffix is deliberate. Prompts are expected to evolve, and the stored
outputs record which `prompt_version` produced them (see
`silver.story_clusters`), so a prompt change is traceable in the eval data. Bump
to `_v2` rather than editing history when the change is significant.
