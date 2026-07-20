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
