"""Iceberg catalog access (SPEC 6.3).

One place that knows how to reach R2 Data Catalog. Credentials come from
config.get_settings(); this module never reads the environment itself.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from pyiceberg.catalog import Catalog, load_catalog

from .config import get_settings

log = logging.getLogger(__name__)


def catalog_properties() -> dict[str, str]:
    settings = get_settings()
    return {
        "type": "rest",
        "uri": settings.r2_catalog_uri,
        "warehouse": settings.r2_warehouse,
        "token": settings.r2_token,
    }


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    """The R2 Data Catalog connection (verified by SETUP.md spike 5.2)."""
    return load_catalog("r2", **catalog_properties())


def ensure_namespace(catalog: Catalog, namespace: str) -> None:
    catalog.create_namespace_if_not_exists(namespace)


# ---------------------------------------------------------------------------
# R2 object storage (SPEC 6.7): the daily MP3, never committed to the repo.
# ---------------------------------------------------------------------------
# Object PUTs use R2's S3-compatible API with account access keys, which are
# distinct from the Data Catalog token above. Credentials come from
# config.get_settings(); this module still never reads the environment.


class AudioStorageError(RuntimeError):
    """R2 object storage is not configured, or an upload failed."""


def _s3_audio_client():
    """boto3 S3 client pointed at R2. Imported lazily so a collector or
    edition run that never touches audio needs neither boto3 nor the keys."""
    import boto3

    settings = get_settings()
    missing = [
        name
        for name, value in (
            ("R2_S3_ENDPOINT", settings.r2_s3_endpoint),
            ("R2_ACCESS_KEY_ID", settings.r2_access_key_id),
            ("R2_SECRET_ACCESS_KEY", settings.r2_secret_access_key),
            ("R2_AUDIO_BUCKET", settings.r2_audio_bucket),
            ("R2_AUDIO_PUBLIC_BASE", settings.r2_audio_public_base),
        )
        if not value
    ]
    if missing:
        raise AudioStorageError(
            "R2 object storage for audio is not configured: missing "
            + ", ".join(missing)
            + ". Set them in .env locally or as Actions secrets in CI (SETUP.md 4.2)."
        )
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_s3_endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )


def audio_public_url(key: str) -> str:
    """The public URL an object key resolves to (SPEC 6.7). The feed
    enclosure and the on-page player both derive from this."""
    base = get_settings().r2_audio_public_base
    if not base:
        raise AudioStorageError("R2_AUDIO_PUBLIC_BASE is not set")
    return f"{base.rstrip('/')}/{key.lstrip('/')}"


def audio_object_exists(key: str) -> bool:
    """True when the audio bucket already holds this key.

    Lets a re-run reuse an MP3 it already produced instead of paying for a
    second script call and a second TTS render.
    """
    client = _s3_audio_client()
    try:
        client.head_object(Bucket=get_settings().r2_audio_bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001 - any miss or error means "regenerate"
        return False


def upload_audio(key: str, data: bytes, *, content_type: str = "audio/mpeg") -> str:
    """Put one object to the audio bucket and return its public URL.

    Idempotent by key: re-running a date overwrites /audio/DATE.mp3 rather
    than accumulating copies, matching the rest of the pipeline's re-run
    behavior.
    """
    client = _s3_audio_client()
    bucket = get_settings().r2_audio_bucket
    try:
        client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    except Exception as exc:  # noqa: BLE001
        raise AudioStorageError(f"failed to upload {key!r} to R2: {exc}") from exc
    return audio_public_url(key)
