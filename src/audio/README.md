# `src/audio/` - the audio brief (text-to-speech)

This subsystem turns the finished `edition.json` into the ~10 minute two-host
audio brief (an MP3) that plays on the site and feeds the podcast. It is the last
AI step of the day, and like everything else it follows rule zero: **one AI call
writes the script, and everything after that is deterministic code.**

## The flow

```
edition.json (already built and validated)
   |
   v  script.py   AI (Haiku): turn the edition into a two-host dialogue (JSON, validated)
   |
   v  tts.py      Gemini multi-speaker text-to-speech -> raw audio -> MP3 (+ exact duration/size)
   |
   v  storage     upload the MP3 to the R2 object bucket at /audio/YYYY-MM-DD.mp3
   |
   v  inject the {url, duration_seconds, size_bytes} "audio" block back into edition.json
```

`run_audio.py` is the entry point that runs all of this and logs the run.

## The files

| File | What it does |
|------|--------------|
| `run_audio.py` | Entry point. Reads the day's edition, builds audio, uploads, injects the audio block. |
| `script.py` | The one AI call: writes a validated two-host dialogue script from the edition. |
| `schema.py` | The dialogue-script schema, written before the prompt. Defines a valid script. |
| `tts.py` | Text-to-speech behind a swappable interface. Default backend is Gemini multi-speaker. |

## Concepts worth understanding

### The script is the only AI call, and it is length-checked

[`script.py`](script.py) asks a small model to produce
`{ "turns": [ {"speaker": "A", "text": "..."}, ... ] }`. The reply is validated
against [`schema.py`](schema.py) (two hosts only, no em dashes, at least four
turns). SPEC asks for a 1,300 to 1,600 word dialogue; that word band is a
*semantic* accept condition checked in code. A script that is valid but off the
band gets one retry that tells the model its length, then is accepted anyway
rather than losing the audio.

### Duration and size are exact, not guessed

[`tts.py`](tts.py) returns the encoded MP3 plus its exact duration. Duration is
computed from the raw PCM sample count *before* encoding, so no MP3 parsing is
needed, and the byte size is just the length of the encoded bytes. Both go into
the `audio` block of `edition.json`. The podcast feed needs a real byte length
because directories reject `length="0"`.

### The text-to-speech backend is swappable

`tts.py` defines a `Synthesizer` interface. The default `GeminiSynthesizer` maps
the two dialogue speakers (A and B) onto two configured Gemini prebuilt voices.
Swapping to a different provider is a config change (`tts_model` and the two
voice names in `pipeline.yaml`) plus a new `Synthesizer` class, not a change to
the caller. MP3 encoding uses `lameenc` (a pip-installable encoder, no system
ffmpeg needed) so the mini PC and CI encode identically.

### Every failure means "publish without audio"

Audio is optional. A missing edition, a fallback edition (which carries no
audio), a script that fails twice, a text-to-speech failure, or an upload failure
all leave the `audio` block `null` and mark the run `partial`. The edition still
publishes, just without a player. Nothing here can block the deploy.

### Re-runs are cheap

If a date's MP3 already exists in R2 and the edition already has an audio block,
`run_audio.py` reuses it (re-deriving the public URL from current config) instead
of paying for a second script call and a second render.
