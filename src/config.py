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
from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class CanonicalUrlConfig(Strict):
    shortener_hosts: tuple[str, ...] = ()

    @field_validator("shortener_hosts")
    @classmethod
    def _lowercase(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(host.lower() for host in value)


class PipelineConfig(Strict):
    collector: CollectorConfig
    canonical_url: CanonicalUrlConfig


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
