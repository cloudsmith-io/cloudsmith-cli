# Copyright 2026 Cloudsmith Ltd
"""
Helper for discovering Cloudsmith custom domains.

This module provides functions to fetch custom domains from the Cloudsmith API
for use in credential helpers. Results are cached on the filesystem.
"""

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..cli.config import get_default_config_path
from ..core.api.exceptions import ApiException
from ..core.api.init import initialise_api
from ..core.api.orgs import list_custom_domains
from ..core.cache_utils import atomic_write_json
from ..core.credentials.models import CredentialResult

logger = logging.getLogger(__name__)

# Cache custom domains for 1 hour
CACHE_TTL_SECONDS = 3600


@dataclass(frozen=True)
class CustomDomain:
    """A structured Cloudsmith custom domain record."""

    host: str
    backend_kind: int | None
    enabled: bool
    validated: bool


def get_cache_dir() -> Path:
    """
    Get the cache directory for custom domains.
    """
    cache_dir = Path(get_default_config_path()) / "custom_domains_cache"
    cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return cache_dir


def get_cache_path(org: str) -> Path:
    """
    Get the cache file path for an organization's custom domains.

    Args:
        org: Organization slug

    Returns:
        Path to cache file
    """
    cache_dir = get_cache_dir()
    safe_org = "".join(c if c.isalnum() or c in "-_" else "_" for c in org)
    return cache_dir / f"{safe_org}.json"


def is_cache_valid(cache_path: Path) -> bool:
    """
    Check if a cache file exists and is still valid.

    Args:
        cache_path: Path to cache file

    Returns:
        bool: True if cache exists and hasn't expired
    """
    if not cache_path.exists():
        return False

    try:
        mtime = cache_path.stat().st_mtime
        age = time.time() - mtime
        return age < CACHE_TTL_SECONDS
    except OSError:
        return False


def read_cache(cache_path: Path) -> list[CustomDomain] | None:
    """
    Read custom domains from cache file.

    Args:
        cache_path: Path to cache file

    Returns:
        List of CustomDomain records or None if cache invalid/missing
    """
    if not is_cache_valid(cache_path):
        return None

    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "domains" in data:
                domains = data["domains"]
                if isinstance(domains, list):
                    # Detect legacy format: non-empty list of strings (old build stored
                    # domains as plain strings, not dicts). Treat as a cache miss so the
                    # caller re-fetches and rewrites in the current dict format.
                    if domains and not any(isinstance(d, dict) for d in domains):
                        logger.debug(
                            "Stale string-format cache detected at %s, treating as miss",
                            cache_path,
                        )
                        return None

                    records = [
                        CustomDomain(
                            host=d["host"],
                            backend_kind=d.get("backend_kind"),
                            enabled=bool(d.get("enabled", False)),
                            validated=bool(d.get("validated", False)),
                        )
                        for d in domains
                        if isinstance(d, dict) and d.get("host")
                    ]
                    logger.debug(
                        "Read %d domains from cache: %s", len(records), cache_path
                    )
                    return records
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Failed to read cache %s: %s", cache_path, exc)

    return None


def write_cache(cache_path: Path, domains: list[CustomDomain]) -> None:
    """Write custom domains to cache file."""
    data = {
        "domains": [
            {
                "host": d.host,
                "backend_kind": d.backend_kind,
                "enabled": d.enabled,
                "validated": d.validated,
            }
            for d in domains
        ],
        "cached_at": time.time(),
    }
    try:
        atomic_write_json(cache_path, data)
        logger.debug("Wrote %d domains to cache: %s", len(domains), cache_path)
    except OSError as exc:
        logger.debug("Failed to write cache %s: %s", cache_path, exc)


def get_custom_domains(  # pylint: disable=too-many-return-statements
    org: str,
    *,
    api_key: str | None = None,
    auth_type: str = "api_key",
    api_host: str | None = None,
) -> list[CustomDomain]:
    """
    Fetch custom domains for a Cloudsmith organization.

    Results are cached on the filesystem for 1 hour to avoid excessive API calls.

    Args:
        org: Organization slug
        api_key: Optional API key/token for authentication
        auth_type: "api_key" (uses X-Api-Key header) or "bearer" (uses Authorization: Bearer)
        api_host: Cloudsmith API host URL (including version). Taken from the SDK
            configuration default when not provided.

    Returns:
        List of CustomDomain records.
        Empty list if API call fails or org has no custom domains.

    Note:
        Only ``ApiException`` is handled here (per-status). Network-layer errors
        (DNS/timeout/SSL/urllib3) are intentionally NOT caught — they propagate to
        the caller. The credential-helper protocol boundary (the click command) and
        the installer are responsible for catching broadly and refusing gracefully,
        so the library stays free of bare ``except Exception`` (reviewer feedback).
    """
    cache_path = get_cache_path(org)
    cached = read_cache(cache_path)
    if cached is not None:
        logger.debug("Using cached custom domains for %s", org)
        return cached

    logger.debug("Fetching custom domains from API for %s", org)

    normalized_auth_type: Literal["api_key", "bearer"] = (
        "bearer" if auth_type == "bearer" else "api_key"
    )
    credential = (
        CredentialResult(
            api_key=api_key,
            source_name="credential-helper",
            auth_type=normalized_auth_type,
        )
        if api_key
        else None
    )
    initialise_api(host=api_host, credential=credential)

    try:
        raw_domains = list_custom_domains(org)
    except ApiException as exc:
        if exc.status in (401, 403):
            # Don't cache auth failures - might work later once authenticated.
            logger.debug(
                "Custom domains API requires auth - assuming no custom domains for %s",
                org,
            )
            return []

        if exc.status == 404:
            # Cache empty result to avoid repeated lookups for a missing org.
            logger.debug("Organization %s not found or has no custom domains", org)
            write_cache(cache_path, [])
            return []

        if exc.status == 402:
            # Custom domains product feature not enabled - treat as none.
            logger.debug("Custom domains not enabled for %s", org)
            write_cache(cache_path, [])
            return []

        logger.debug("Failed to fetch custom domains for %s: HTTP %s", org, exc.status)
        return []

    records = [
        CustomDomain(
            host=d["host"],
            backend_kind=d.get("backend_kind"),
            enabled=bool(d.get("enabled", False)),
            validated=bool(d.get("validated", False)),
        )
        for d in raw_domains
        if d.get("host")
    ]

    logger.debug("Fetched %d custom domains for %s", len(records), org)
    write_cache(cache_path, records)
    return records


def get_format_domains(
    org: str,
    backend_kind: int,
    *,
    api_key: str | None = None,
    auth_type: str = "api_key",
    api_host: str | None = None,
) -> list[str]:
    """
    Return enabled and validated custom domain hostnames for a specific backend format.

    Args:
        org: Organization slug
        backend_kind: BackendKind int value (e.g. BackendKind.DOCKER == 6)
        api_key: Optional API key/token for authentication
        auth_type: "api_key" or "bearer"
        api_host: Cloudsmith API host URL

    Returns:
        List of hostnames that are enabled, validated, and match the given backend_kind.
    """
    domains = get_custom_domains(
        org, api_key=api_key, auth_type=auth_type, api_host=api_host
    )
    return [
        d.host
        for d in domains
        if d.backend_kind == int(backend_kind) and d.enabled and d.validated
    ]
