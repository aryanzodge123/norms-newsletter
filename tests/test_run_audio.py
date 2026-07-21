"""The audio orchestrator (SPEC 6.7). Every failure is contained to
"publish without audio" (SPEC 7). Fully offline: a fake synthesizer, a fake
upload, and a stubbed Anthropic client.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from src.config import REPO_ROOT, AudioConfig
from src.audio import run_audio
from src.audio.schema import validate_script
from src.audio.tts import Synthesized, TTSError
from src.editor.schema import EditionInvalid
from src.storage import AudioStorageError

from tests.test_audio_script import make_script_json
from tests.test_writer_stage import FakeClient


@pytest.fixture
def config() -> AudioConfig:
    return AudioConfig(
        script_model="claude-haiku-4-5-20251001",
        max_retries=1,
        tts_model="gemini-2.5-flash-preview-tts",
        speaker_a_voice="Kore",
        speaker_b_voice="Puck",
        min_words=10,
        max_words=20,
    )


def load_fixture(name: str) -> dict:
    return json.loads((REPO_ROOT / "site" / "fixtures" / name).read_text())


class FakeSynth:
    def __init__(self, rendered=None, error=None):
        self.rendered = rendered
        self.error = error
        self.calls = 0

    def synthesize(self, script):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.rendered


def ok_client() -> FakeClient:
    return FakeClient([make_script_json(15)])


def rendered() -> Synthesized:
    return Synthesized(audio_mpeg=b"ID3fakebytes", duration_seconds=540)


# --------------------------------------------------------------------------
# build_audio
# --------------------------------------------------------------------------
def test_happy_path_returns_audio_block(config) -> None:
    uploaded = {}

    def fake_upload(key, data):
        uploaded["key"] = key
        uploaded["len"] = len(data)
        return "https://cdn.invalid/audio/2026-07-19.mp3"

    edition = load_fixture("normal.json")
    result = run_audio.build_audio(
        edition, config, client=ok_client(), synthesizer=FakeSynth(rendered()),
        upload=fake_upload, exists=lambda key: False,
    )
    assert result.audio == {
        "url": "https://cdn.invalid/audio/2026-07-19.mp3",
        "duration_seconds": 540,
        "size_bytes": len(b"ID3fakebytes"),
    }
    assert uploaded["key"] == "audio/2026-07-19.mp3"


def test_existing_audio_is_reused_without_spending(config) -> None:
    """A re-publish must not pay for a second script call and TTS render when
    the date's MP3 is already in the bucket."""
    edition = load_fixture("normal.json")
    edition["audio"] = {
        "url": "https://old-base.invalid/audio/2026-07-19.mp3",
        "duration_seconds": 548,
        "size_bytes": 8781234,
    }
    synth = FakeSynth(rendered())
    client = ok_client()
    result = run_audio.build_audio(
        edition,
        config,
        client=client,
        synthesizer=synth,
        exists=lambda key: True,
        public_url=lambda key: f"https://new-base.invalid/{key}",
    )
    # URL refreshed from current config, measurements kept, nothing spent.
    assert result.audio == {
        "url": "https://new-base.invalid/audio/2026-07-19.mp3",
        "duration_seconds": 548,
        "size_bytes": 8781234,
    }
    assert result.cost_usd == 0.0
    assert synth.calls == 0
    assert client.messages.calls == 0


def test_missing_object_regenerates(config) -> None:
    """An audio block whose object is gone from the bucket is rebuilt."""
    edition = load_fixture("normal.json")
    edition["audio"] = {"url": "https://x.invalid/a.mp3", "duration_seconds": 1, "size_bytes": 1}
    synth = FakeSynth(rendered())
    result = run_audio.build_audio(
        edition, config, client=ok_client(), synthesizer=synth,
        exists=lambda key: False, upload=lambda k, d: "https://new.invalid/" + k,
    )
    assert synth.calls == 1
    assert result.audio["duration_seconds"] == 540


def test_fallback_edition_has_no_audio(config) -> None:
    result = run_audio.build_audio(
        load_fixture("fallback.json"), config, client=ok_client(), synthesizer=FakeSynth(rendered())
    )
    assert result.audio is None
    assert "fallback" in result.note


def test_dry_run_makes_no_tts_call(config) -> None:
    synth = FakeSynth(rendered())
    result = run_audio.build_audio(
        load_fixture("normal.json"), config, client=ok_client(), synthesizer=synth, dry_run=True
    )
    assert result.audio is None
    assert synth.calls == 0
    assert "dry run" in result.note


def test_tts_failure_is_contained(config) -> None:
    result = run_audio.build_audio(
        load_fixture("normal.json"),
        config,
        client=ok_client(),
        synthesizer=FakeSynth(error=TTSError("no encoder")),
        exists=lambda key: False,
    )
    assert result.audio is None
    assert "TTS failed" in result.note


def test_upload_failure_is_contained(config) -> None:
    def boom(key, data):
        raise AudioStorageError("bucket missing")

    result = run_audio.build_audio(
        load_fixture("normal.json"),
        config,
        client=ok_client(),
        synthesizer=FakeSynth(rendered()),
        upload=boom,
        exists=lambda key: False,
    )
    assert result.audio is None
    assert "upload failed" in result.note


def test_script_failure_is_contained(config) -> None:
    bad_client = FakeClient(["not json", json.dumps({"turns": []})])
    result = run_audio.build_audio(
        load_fixture("normal.json"), config, client=bad_client,
        synthesizer=FakeSynth(rendered()), exists=lambda key: False,
    )
    assert result.audio is None
    assert "script failed" in result.note


def _rendered_costing(cost: float) -> Synthesized:
    return Synthesized(audio_mpeg=b"ID3fakebytes", duration_seconds=540, cost_usd=cost)


def test_build_audio_sums_script_and_tts_cost(config) -> None:
    # A dry run pays only the script call; a full run adds the TTS render cost,
    # so the difference is exactly the render's cost_usd.
    script_only = run_audio.build_audio(
        load_fixture("normal.json"), config, client=ok_client(), dry_run=True
    )
    full = run_audio.build_audio(
        load_fixture("normal.json"), config, client=ok_client(),
        synthesizer=FakeSynth(_rendered_costing(0.037)),
        upload=lambda k, d: "https://x.invalid/" + k, exists=lambda key: False,
    )
    assert full.cost_usd == pytest.approx(script_only.cost_usd + 0.037)
    assert "tts $0.0370" in full.note


def test_upload_failure_still_counts_tts_cost(config) -> None:
    def boom(key, data):
        raise AudioStorageError("bucket missing")

    script_only = run_audio.build_audio(
        load_fixture("normal.json"), config, client=ok_client(), dry_run=True
    )
    full = run_audio.build_audio(
        load_fixture("normal.json"), config, client=ok_client(),
        synthesizer=FakeSynth(_rendered_costing(0.037)), upload=boom,
        exists=lambda key: False,
    )
    assert full.audio is None
    assert full.cost_usd == pytest.approx(script_only.cost_usd + 0.037)


# --------------------------------------------------------------------------
# inject_audio
# --------------------------------------------------------------------------
def test_inject_audio_keeps_edition_valid() -> None:
    edition = load_fixture("normal.json")
    out = run_audio.inject_audio(
        edition, {"url": "https://x.invalid/a.mp3", "duration_seconds": 10, "size_bytes": 100}
    )
    assert out["audio"]["size_bytes"] == 100


def test_inject_null_audio_is_valid() -> None:
    out = run_audio.inject_audio(load_fixture("normal.json"), None)
    assert out["audio"] is None


def test_inject_audio_without_size_is_rejected() -> None:
    with pytest.raises(EditionInvalid):
        run_audio.inject_audio(
            load_fixture("normal.json"),
            {"url": "https://x.invalid/a.mp3", "duration_seconds": 10},
        )


# --------------------------------------------------------------------------
# run(): file IO + status, with build_audio and the run_log stubbed
# --------------------------------------------------------------------------
def _wire_run(monkeypatch, tmp_path, config, audio_result):
    edition = load_fixture("normal.json")
    edition["audio"] = None
    path = tmp_path / "2026-07-19.json"
    path.write_text(json.dumps(edition))

    monkeypatch.setattr(run_audio, "edition_path", lambda d: path)
    monkeypatch.setattr(run_audio, "get_pipeline", lambda: type("P", (), {"audio": config})())
    monkeypatch.setattr(run_audio, "get_client", lambda: ok_client())
    monkeypatch.setattr(run_audio, "build_audio", lambda *a, **k: audio_result)
    logged = {}
    monkeypatch.setattr(run_audio, "_log_run", lambda *a, **k: logged.setdefault("called", True))
    return path, logged


def test_run_writes_audio_block(monkeypatch, tmp_path, config) -> None:
    result = run_audio.AudioResult(
        {"url": "https://x.invalid/a.mp3", "duration_seconds": 540, "size_bytes": 999}, 0.01, 12, "ok"
    )
    path, logged = _wire_run(monkeypatch, tmp_path, config, result)
    rc = run_audio.run(date(2026, 7, 19))
    assert rc == 0
    written = json.loads(path.read_text())
    assert written["audio"]["size_bytes"] == 999
    assert logged["called"]


def test_run_with_no_audio_leaves_null(monkeypatch, tmp_path, config) -> None:
    result = run_audio.AudioResult(None, 0.01, 0, "TTS failed")
    path, _ = _wire_run(monkeypatch, tmp_path, config, result)
    rc = run_audio.run(date(2026, 7, 19))
    assert rc == 0  # partial, not failed: the edition still publishes
    assert json.loads(path.read_text())["audio"] is None


def test_run_fallback_edition_is_contained_noop(monkeypatch, tmp_path, config) -> None:
    # A fallback edition has no audio field (FallbackEdition forbids it), so
    # run() must not inject audio=None: that would fail schema validation, fail
    # the step, and take the whole publish down with it (SPEC 7 says audio
    # failure is contained to "publish without an audio row"). Exercised at the
    # run() level because build_audio already bows out; the crash was in run().
    edition = load_fixture("fallback.json")
    original = json.dumps(edition, indent=2, ensure_ascii=False) + "\n"
    path = tmp_path / "2026-07-21.json"
    path.write_text(original)

    monkeypatch.setattr(run_audio, "edition_path", lambda d: path)
    monkeypatch.setattr(run_audio, "get_pipeline", lambda: type("P", (), {"audio": config})())
    monkeypatch.setattr(run_audio, "get_client", lambda: ok_client())
    monkeypatch.setattr(
        run_audio,
        "build_audio",
        lambda *a, **k: run_audio.AudioResult(None, 0.0, 0, "fallback edition carries no audio"),
    )
    captured = {}
    monkeypatch.setattr(
        run_audio, "_log_run", lambda *a, **k: captured.update(status=a[2])
    )

    rc = run_audio.run(date(2026, 7, 21))

    assert rc == 0  # contained, not failed: the fallback edition still publishes
    assert captured["status"] == "partial"
    assert path.read_text() == original  # file untouched, no audio key added


def test_run_missing_edition_is_noop(monkeypatch, tmp_path, config) -> None:
    monkeypatch.setattr(run_audio, "edition_path", lambda d: tmp_path / "nope.json")
    monkeypatch.setattr(run_audio, "get_pipeline", lambda: type("P", (), {"audio": config})())
    monkeypatch.setattr(run_audio, "_log_run", lambda *a, **k: None)
    assert run_audio.run(date(2026, 7, 19)) == 0
