# `spikes/` - standalone smoke checks

A "spike" here is a small, throwaway script that verifies one credential or one
dependency works **before** you rely on it in the pipeline. They are not imported
by `src/` and are not part of the pipeline; they exist so that when something
breaks you can tell whether the problem is your code or your setup.

They are referenced by [`../SETUP.md`](../SETUP.md) (Part 5), which walks a new
machine through running them during initial setup. The pre-launch migration plan
(SPEC section 13) re-runs them to confirm new credentials work.

## The checks

| File | Confirms |
|------|----------|
| `check_iceberg.py` | You can reach the R2 Iceberg catalog and create/read/write a test table |
| `check_anthropic.py` | Your Anthropic API key works and you can call a model |
| `check_embeddings.py` | `sentence-transformers` installs and can embed text locally (uses a small model to prove the stack works) |
| `check_tts.py` | Your Gemini key works and text-to-speech-capable models are visible to your account |

## How to use them

Run one directly when you suspect a setup or credential problem:

```bash
uv run python spikes/check_iceberg.py
```

If a spike passes but the pipeline still fails, the problem is in the code. If a
spike fails, fix the credential or install before going further. That is the
whole point of keeping them separate from `src/`.
