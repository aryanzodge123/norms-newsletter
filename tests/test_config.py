"""Configuration loading (SPEC 6.10).

A malformed registry or a missing credential must fail at startup, not
halfway through a collection run.
"""

from __future__ import annotations

import pytest

from src.config import (
    ConfigError,
    Settings,
    load_pipeline,
    load_sources,
)

VALID_SOURCES = """
- name: hackernews
  adapter: adapters.hackernews.HackerNewsAdapter
  topic_hint: tech
  enabled: true
  max_items_per_run: 40
"""

VALID_PIPELINE = """
collector:
  since_window_hours: 6
enrich:
  enabled: true
  min_chars: 600
  timeout_seconds: 10.0
  max_concurrency: 8
  max_bytes: 2000000
  skip_hosts:
    - news.google.com
silver:
  embedding_model: BAAI/bge-small-en-v1.5
  embed_chars: 500
  cluster_threshold: 0.82
  scoring_model: claude-haiku-4-5-20251001
  scoring_max_retries: 1
editor:
  editor_model: claude-sonnet-4-5-20250929
  writer_model: claude-haiku-4-5-20251001
  max_retries: 1
  writer_concurrency: 6
  min_clusters_for_normal: 12
  min_clusters_for_quiet: 3
  min_grounding_chars: 400
  readability_max_passes: 2
audio:
  script_model: claude-haiku-4-5-20251001
  max_retries: 1
  tts_model: gemini-2.5-flash-preview-tts
  speaker_a_voice: Kore
  speaker_b_voice: Puck
  min_words: 1300
  max_words: 1600
archive:
  prior_mention_lookback_days: 30
  continuing_coverage_lookback_days: 7
  headline_repeat_threshold: 0.80
  snapshot_expiry_days: 7
canonical_url:
  shortener_hosts:
    - t.co
"""


def write(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_the_repo_config_actually_loads() -> None:
    """The committed config/ must be valid, not just the test fixtures."""
    sources = load_sources()
    pipeline = load_pipeline()
    assert {s.name for s in sources} >= {"hackernews", "arstechnica"}
    assert pipeline.collector.since_window_hours > 0
    assert "t.co" in pipeline.canonical_url.shortener_hosts


def test_loads_a_valid_registry(tmp_path) -> None:
    sources = load_sources(write(tmp_path, "sources.yaml", VALID_SOURCES))
    assert sources[0].name == "hackernews"
    assert sources[0].max_items_per_run == 40


def test_rejects_an_unknown_key(tmp_path) -> None:
    text = VALID_SOURCES + "  priority: high\n"
    with pytest.raises(ConfigError, match="priority"):
        load_sources(write(tmp_path, "sources.yaml", text))


def test_rejects_a_malformed_adapter_path(tmp_path) -> None:
    text = VALID_SOURCES.replace(
        "adapters.hackernews.HackerNewsAdapter", "hackernews"
    )
    with pytest.raises(ConfigError, match="dotted path"):
        load_sources(write(tmp_path, "sources.yaml", text))


def test_rejects_duplicate_source_names(tmp_path) -> None:
    with pytest.raises(ConfigError, match="duplicate"):
        load_sources(write(tmp_path, "sources.yaml", VALID_SOURCES + VALID_SOURCES))


def test_rejects_a_non_positive_item_cap(tmp_path) -> None:
    text = VALID_SOURCES.replace("max_items_per_run: 40", "max_items_per_run: 0")
    with pytest.raises(ConfigError):
        load_sources(write(tmp_path, "sources.yaml", text))


def test_rejects_an_empty_registry(tmp_path) -> None:
    with pytest.raises(ConfigError, match="non-empty list"):
        load_sources(write(tmp_path, "sources.yaml", "[]"))


def test_rejects_invalid_yaml(tmp_path) -> None:
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_sources(write(tmp_path, "sources.yaml", "- name: [unclosed\n"))


def test_reports_a_missing_config_file(tmp_path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_sources(tmp_path / "nope.yaml")


def test_pipeline_lowercases_shortener_hosts(tmp_path) -> None:
    text = VALID_PIPELINE.replace("- t.co", "- T.CO")
    pipeline = load_pipeline(write(tmp_path, "pipeline.yaml", text))
    assert pipeline.canonical_url.shortener_hosts == ("t.co",)


def test_editor_config_loads(tmp_path) -> None:
    pipeline = load_pipeline(write(tmp_path, "pipeline.yaml", VALID_PIPELINE))
    assert pipeline.editor.min_grounding_chars == 400
    assert pipeline.editor.editor_model.startswith("claude-sonnet")


def test_enrich_config_loads(tmp_path) -> None:
    pipeline = load_pipeline(write(tmp_path, "pipeline.yaml", VALID_PIPELINE))
    assert pipeline.enrich.enabled is True
    assert pipeline.enrich.min_chars == 600
    # Google News links are opaque shims; fetching one returns no article.
    assert "news.google.com" in pipeline.enrich.skip_hosts


def test_audio_config_loads(tmp_path) -> None:
    pipeline = load_pipeline(write(tmp_path, "pipeline.yaml", VALID_PIPELINE))
    assert pipeline.audio.min_words == 1300
    assert pipeline.audio.max_words == 1600
    assert pipeline.audio.tts_model.startswith("gemini")


def test_audio_rejects_inverted_word_band(tmp_path) -> None:
    text = VALID_PIPELINE.replace("min_words: 1300", "min_words: 2000")
    with pytest.raises(ConfigError, match="min_words"):
        load_pipeline(write(tmp_path, "pipeline.yaml", text))


def test_editor_rejects_quiet_above_normal_threshold(tmp_path) -> None:
    text = VALID_PIPELINE.replace("min_clusters_for_quiet: 3", "min_clusters_for_quiet: 20")
    with pytest.raises(ConfigError, match="min_clusters_for_quiet"):
        load_pipeline(write(tmp_path, "pipeline.yaml", text))


def test_missing_credentials_fail_loudly(monkeypatch) -> None:
    for key in ("R2_CATALOG_URI", "R2_WAREHOUSE", "R2_TOKEN"):
        monkeypatch.setenv(key, "")
    monkeypatch.setattr("src.config.load_dotenv", lambda *a, **k: None)
    with pytest.raises(ConfigError, match="missing required credentials"):
        Settings.from_env()


def test_settings_read_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("R2_CATALOG_URI", "https://catalog.example")
    monkeypatch.setenv("R2_WAREHOUSE", "warehouse")
    monkeypatch.setenv("R2_TOKEN", "token")
    monkeypatch.delenv("NEWSAPI_KEY", raising=False)
    monkeypatch.setattr("src.config.load_dotenv", lambda *a, **k: None)

    settings = Settings.from_env()
    assert settings.r2_catalog_uri == "https://catalog.example"
    # later-milestone credentials stay optional so an M1 run does not
    # demand an M6 key
    assert settings.newsapi_key is None
