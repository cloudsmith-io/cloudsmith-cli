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

from ..cli.config import get_default_config_path
from ..core.api.exceptions import ApiException
from ..core.api.init import initialise_api
from ..core.api.orgs import list_custom_domains
from ..core.cache_utils import atomic_write_json
from ..core.credentials.models import CredentialResult
from .default_domains import DomainScope

logger = logging.getLogger(__name__)

# Custom domains change rarely, so the cache is long-lived; `--refresh`
# bypasses it when a domain has just been added or validated.
CACHE_TTL_SECONDS = 7 * 24 * 3600

# Bump when the cached record shape changes: an older document is a miss, not
# a record with the new fields defaulted.
CACHE_FORMAT_VERSION = 2


@dataclass(frozen=True)
class CustomDomain:
    """A structured Cloudsmith custom domain record."""

    host: str
    backend_kind: int | None
    enabled: bool
    validated: bool
    org: str
    repository: str | None = None
    repository_only: bool = False

    @property
    def scope(self) -> DomainScope:
        """What this domain is bound to.

        ``repository_only`` without a repository is a server-side
        contradiction; treating it as repository-scoped would build a URL with
        no identifying path segment at all, so it degrades to organisation.
        """
        if self.repository_only and self.repository:
            return DomainScope.REPOSITORY
        return DomainScope.ORGANIZATION


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


def _repository_slug(raw) -> str | None:
    """Return the repository slug from an API or cache payload.

    The API nests the repository as ``{"name": ..., "slug": ...}``; the cache
    stores the slug flat.  One reader serves both.
    """
    if isinstance(raw, dict):
        return raw.get("slug") or None
    if isinstance(raw, str):
        return raw or None
    return None


def _record_from_payload(raw: dict, org: str) -> CustomDomain:
    """Build a CustomDomain from an API or cache payload for *org*."""
    return CustomDomain(
        host=raw["host"],
        backend_kind=raw.get("backend_kind"),
        enabled=bool(raw.get("enabled", False)),
        validated=bool(raw.get("validated", False)),
        org=org,
        repository=_repository_slug(raw.get("repository")),
        repository_only=bool(raw.get("repository_only", False)),
    )


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
            if (
                isinstance(data, dict)
                and data.get("format_version") != CACHE_FORMAT_VERSION
            ):
                logger.debug(
                    "Cache %s has format version %s, expected %s - treating as miss",
                    cache_path,
                    data.get("format_version"),
                    CACHE_FORMAT_VERSION,
                )
                return None
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
                        _record_from_payload(d, d.get("org", ""))
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
        "format_version": CACHE_FORMAT_VERSION,
        "domains": [
            {
                "host": d.host,
                "backend_kind": d.backend_kind,
                "enabled": d.enabled,
                "validated": d.validated,
                "org": d.org,
                "repository": d.repository,
                "repository_only": d.repository_only,
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
    credential: CredentialResult | None = None,
    api_host: str | None = None,
    refresh: bool = False,
    strict: bool = False,
) -> list[CustomDomain]:
    """
    Fetch custom domains for a Cloudsmith organization.

    Results are cached on the filesystem for 7 days to avoid excessive API calls.

    Args:
        org: Organization slug
        credential: Optional resolved credential for authentication; it carries
            its own auth scheme (X-Api-Key vs Authorization: Bearer)
        api_host: Cloudsmith API host URL (including version). Taken from the SDK
            configuration default when not provided.
        refresh: When ``True``, skip the cache read and always fetch from the API.
            The fresh result is still written to the cache.
        strict: When ``True``, a failed lookup re-raises its ``ApiException``
            instead of degrading to an empty list. For callers that present
            results to a user (``credential-helper domains``), which must not
            render a typo'd org, a missing permission or an unreachable API as
            "no custom domains". A 402 still returns ``[]`` even in strict
            mode — the feature being disabled genuinely means there are none.
            Failures are never cached, so a strict lookup can be served from
            the cache without risking a cached failure being reported as
            success.

    Returns:
        List of CustomDomain records.
        Empty list if the org has no custom domains, or (unless ``strict``)
        if the API call fails.

    Note:
        The API layer wraps transport failures (DNS/timeout/SSL) into
        ``ApiException`` too, so every failure mode lands in the handler
        below. The default is best-effort (helpers degrade rather than break
        the wrapped tool); pass ``strict=True`` to fail loudly instead.
    """
    cache_path = get_cache_path(org)
    cached = None if refresh else read_cache(cache_path)
    if cached is not None:
        logger.debug("Using cached custom domains for %s", org)
        return cached

    logger.debug("Fetching custom domains from API for %s", org)

    initialise_api(host=api_host, credential=credential)

    try:
        raw_domains = list_custom_domains(org)
    except ApiException as exc:
        if strict and exc.status != 402:
            raise
        if exc.status in (401, 403):
            # Don't cache auth failures - might work later once authenticated.
            logger.debug(
                "Custom domains API requires auth - assuming no custom domains for %s",
                org,
            )
            return []

        if exc.status == 404:
            logger.debug("Organization %s not found or has no custom domains", org)
            return []

        if exc.status == 402:
            # Custom domains product feature not enabled - treat as none.
            logger.debug("Custom domains not enabled for %s", org)
            return []

        logger.debug("Failed to fetch custom domains for %s: HTTP %s", org, exc.status)
        return []

    records = [_record_from_payload(d, org) for d in raw_domains if d.get("host")]

    logger.debug("Fetched %d custom domains for %s", len(records), org)
    write_cache(cache_path, records)
    return records


def get_format_domains(
    org: str,
    backend_kind: int,
    *,
    credential: CredentialResult | None = None,
    api_host: str | None = None,
    refresh: bool = False,
) -> list[str]:
    """
    Return enabled and validated custom domain hostnames for a specific backend format.

    Args:
        org: Organization slug
        backend_kind: BackendKind int value (e.g. BackendKind.DOCKER == 6)
        credential: Optional resolved credential for authentication
        api_host: Cloudsmith API host URL
        refresh: When ``True``, bypass the cache and fetch fresh data from the API.

    Returns:
        List of hostnames that are enabled, validated, and match the given backend_kind.
    """
    domains = get_custom_domains(
        org, credential=credential, api_host=api_host, refresh=refresh
    )
    return [
        d.host
        for d in domains
        if d.backend_kind == int(backend_kind) and d.enabled and d.validated
    ]
