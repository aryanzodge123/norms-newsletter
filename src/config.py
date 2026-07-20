"""Configuration and secrets loading (SPEC 6.10).

This is the only module in the codebase that reads environment variables.
Everything else imports typed settings from here. A bare os.environ or
os.getenv anywhere else is a bug.

Configuration is validated at load time so a malformed registry or a
missing credential fails loudly at startup rather than mid-run.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"

# "adapters.hackernews.HackerNewsAdapter": at least module.Class, resolved
# under src/ by the collector. Kept in the SPEC 6.1 form in the yaml.
ADAPTER_PATH_RE = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)+\.[A-Z]\w*$")


class ConfigError(RuntimeError):
    """Raised when configuration is missing, malformed, or incomplete."""


class Strict(BaseModel):
    """Base model that rejects unknown keys, so typos fail loudly."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceConfig(Strict):
    """One entry in the adapter registry (SPEC 6.1)."""

    name: str
    adapter: str
    topic_hint: str
    enabled: bool = True
    max_items_per_run: int = Field(gt=0)
    # Optional per-source feed/endpoint URL. The generic RSS adapter
    # (adapters.rss.RSSAdapter) is one class serving many feeds, so the feed
    # location lives in the registry rather than in the code. Bespoke
    # adapters that hardcode their own endpoint ignore this. Proposed SPEC
    # 6.1 addition (M6).
    feed_url: str | None = None

    @field_validator("adapter")
    @classmethod
    def _valid_adapter_path(cls, value: str) -> str:
        if not ADAPTER_PATH_RE.match(value):
            raise ValueError(
                f"adapter must be a dotted path ending in a class name, got {value!r}"
            )
        return value


class CollectorConfig(Strict):
    since_window_hours: int = Field(gt=0)


class EnrichConfig(Strict):
    """Article-text enrichment (SPEC 6.1 body_excerpt).

    Adapters store the feed's summary, which is a one-line blurb on most
    sources, leaving the writer stage nothing to ground on (decision #16).
    This step fetches the item's canonical_url and extracts the main article
    text so body_excerpt is what SPEC 6.1 says it is. Every failure falls
    back to the adapter-supplied summary, so enrichment can never fail a
    collection run.
    """

    enabled: bool = True
    # Only fetch when the adapter's excerpt is thinner than this. An item
    # that already carries real text is left alone.
    min_chars: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0)
    max_concurrency: int = Field(gt=0)
    # Hard cap on a response body, so one pathological page cannot stall or
    # balloon a run.
    max_bytes: int = Field(gt=0)
    # Hosts that are pointless or harmful to fetch. Google News RSS links are
    # opaque JS shims that carry no publisher URL and no article text.
    skip_hosts: tuple[str, ...] = ()

    @field_validator("skip_hosts")
    @classmethod
    def _lowercase(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(host.lower() for host in value)


class SilverConfig(Strict):
    """Silver processing thresholds and models (SPEC 6.4)."""

    embedding_model: str
    embed_chars: int = Field(gt=0)
    cluster_threshold: float = Field(gt=0.0, le=1.0)
    scoring_model: str
    scoring_max_retries: int = Field(ge=0)


class EditorConfig(Strict):
    """Edition generation settings (SPEC 6.5)."""

    editor_model: str
    writer_model: str
    max_retries: int = Field(ge=0)
    writer_concurrency: int = Field(gt=0)
    min_clusters_for_normal: int = Field(gt=0)
    min_clusters_for_quiet: int = Field(ge=0)
    min_grounding_chars: int = Field(ge=0)
    # SPEC 6.5 describes one automatic revision pass for the readability
    # gate. Measured on real editions, one pass lands just over the line
    # (11.3 to 9.15), so the count is configurable and defaults to 2. Each
    # pass costs one small simplify call plus one writer call per failing
    # story, so this is the knob that trades money for reading grade.
    readability_max_passes: int = Field(ge=1, default=2)

    @model_validator(mode="after")
    def _thresholds_ordered(self) -> EditorConfig:
        if self.min_clusters_for_quiet > self.min_clusters_for_normal:
            raise ValueError(
                "min_clusters_for_quiet must not exceed min_clusters_for_normal, "
                f"got {self.min_clusters_for_quiet} > {self.min_clusters_for_normal}"
            )
        return self


class AudioConfig(Strict):
    """Audio build settings (SPEC 6.7, decision #4).

    The dialogue script is the one AI call; TTS, duration, upload and the
    audio block are deterministic code. Model ids are pinned for the same
    eval-stability reason M2/M3 pinned theirs. Speaker voices are Gemini
    prebuilt voice names behind the swappable TTS interface.
    """

    script_model: str
    max_retries: int = Field(ge=0)
    tts_model: str
    speaker_a_voice: str
    speaker_b_voice: str
    # SPEC 6.7: "1,300-1,600 words". Enforced in code on the validated
    # script, so a script outside the band is a failure the caller contains
    # (publish without audio), not something the model is trusted to hold.
    min_words: int = Field(gt=0)
    max_words: int = Field(gt=0)

    @model_validator(mode="after")
    def _word_band_ordered(self) -> AudioConfig:
        if self.min_words > self.max_words:
            raise ValueError(
                f"min_words must not exceed max_words, got {self.min_words} > {self.max_words}"
            )
        return self


class CanonicalUrlConfig(Strict):
    shortener_hosts: tuple[str, ...] = ()

    @field_validator("shortener_hosts")
    @classmethod
    def _lowercase(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(host.lower() for host in value)


class ArchiveConfig(Strict):
    """Archival job settings (SPEC 6.9)."""

    # How far back the writer stage looks in gold for prior coverage of a
    # story (SPEC 6.5 stage 2). cluster_id is not stable across days, so the
    # match is semantic, over this window, against clusters that were
    # actually published.
    prior_mention_lookback_days: int = Field(gt=0)
    # SPEC 6.9: expire snapshots older than this many days on the tables the
    # archival job touches, so metadata does not grow without bound as daily
    # partitions are dropped.
    snapshot_expiry_days: int = Field(gt=0)


class PipelineConfig(Strict):
    collector: CollectorConfig
    enrich: EnrichConfig
    silver: SilverConfig
    editor: EditorConfig
    audio: AudioConfig
    canonical_url: CanonicalUrlConfig
    archive: ArchiveConfig


class Settings(Strict):
    """Credentials, read from the environment exactly once.

    R2 values are required because M1 cannot write bronze without them.
    Later-milestone keys are optional here and are required by the module
    that uses them, so an M1 run does not demand an M6 credential.
    """

    r2_catalog_uri: str
    r2_warehouse: str
    r2_token: str

    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    newsapi_key: str | None = None
    finnhub_key: str | None = None
    fred_key: str | None = None
    healthchecks_publish_url: str | None = None
    healthchecks_collect_url: str | None = None

    # R2 object storage for the daily MP3 (SPEC 6.7: "MP3 to R2 at
    # /audio/YYYY-MM-DD.mp3; the repo never stores audio"). Distinct from the
    # R2 Data Catalog above: object PUTs use the S3 API with account access
    # keys, not the catalog token. Optional here, required by src/audio.
    # r2_audio_public_base is the public URL prefix the enclosure/player link
    # derives from; it is environment-specific and pairs with the bucket, so
    # it lives with the credentials rather than in the committed yaml. Rule 6
    # governs the site's own URLs; the audio enclosure is R2-hosted per SPEC
    # 6.7 (M6 clarification).
    r2_s3_endpoint: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_audio_bucket: str | None = None
    r2_audio_public_base: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(REPO_ROOT / ".env")
        required = ("R2_CATALOG_URI", "R2_WAREHOUSE", "R2_TOKEN")
        missing = [key for key in required if not os.environ.get(key)]
        if missing:
            raise ConfigError(
                "missing required credentials: "
                + ", ".join(missing)
                + ". Set them in .env locally or as Actions secrets in CI (SETUP.md 4.2)."
            )
        return cls(
            r2_catalog_uri=os.environ["R2_CATALOG_URI"],
            r2_warehouse=os.environ["R2_WAREHOUSE"],
            r2_token=os.environ["R2_TOKEN"],
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            gemini_api_key=os.environ.get("GEMINI_API_KEY"),
            newsapi_key=os.environ.get("NEWSAPI_KEY"),
            finnhub_key=os.environ.get("FINNHUB_KEY"),
            fred_key=os.environ.get("FRED_KEY"),
            healthchecks_publish_url=os.environ.get("HEALTHCHECKS_PUBLISH_URL"),
            healthchecks_collect_url=os.environ.get("HEALTHCHECKS_COLLECT_URL"),
            r2_s3_endpoint=os.environ.get("R2_S3_ENDPOINT"),
            r2_access_key_id=os.environ.get("R2_ACCESS_KEY_ID"),
            r2_secret_access_key=os.environ.get("R2_SECRET_ACCESS_KEY"),
            r2_audio_bucket=os.environ.get("R2_AUDIO_BUCKET"),
            r2_audio_public_base=os.environ.get("R2_AUDIO_PUBLIC_BASE"),
        )


def _read_yaml(path: Path):
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name} is not valid YAML: {exc}") from exc


def load_sources(path: Path | None = None) -> tuple[SourceConfig, ...]:
    """Load and validate the adapter registry."""
    path = path or CONFIG_DIR / "sources.yaml"
    raw = _read_yaml(path)
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{path.name} must be a non-empty list of source entries")
    try:
        sources = tuple(SourceConfig(**entry) for entry in raw)
    except Exception as exc:
        raise ConfigError(f"{path.name}: {exc}") from exc

    names = [s.name for s in sources]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ConfigError(f"{path.name}: duplicate source names {sorted(duplicates)}")
    return sources


def load_pipeline(path: Path | None = None) -> PipelineConfig:
    """Load and validate operational configuration."""
    path = path or CONFIG_DIR / "pipeline.yaml"
    raw = _read_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError(f"{path.name} must be a mapping")
    try:
        return PipelineConfig(**raw)
    except Exception as exc:
        raise ConfigError(f"{path.name}: {exc}") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


@lru_cache(maxsize=1)
def get_sources() -> tuple[SourceConfig, ...]:
    return load_sources()


@lru_cache(maxsize=1)
def get_pipeline() -> PipelineConfig:
    return load_pipeline()


def enabled_sources() -> tuple[SourceConfig, ...]:
    return tuple(s for s in get_sources() if s.enabled)
