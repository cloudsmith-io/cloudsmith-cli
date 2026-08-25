# Copyright 2026 Cloudsmith Ltd
"""
Helper for discovering Cloudsmith custom domains.

This module provides functions to fetch custom domains from the Cloudsmith API
for use in credential helpers.

Results are cached on the filesystem. Custom domains change rarely, so the
cache is long-lived and ``--refresh`` bypasses it when one has just been added
or validated. Bump ``CACHE_FORMAT_VERSION`` when the cached record shape
changes, so an older document reads as a miss rather than as a record with the
new fields defaulted.
"""

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from ..cli.config import get_default_config_path
from ..core.cache_utils import atomic_write_json
from ..core.credentials.models import CredentialResult
from .default_domains import DomainType, domain_type_from_server

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 7 * 24 * 3600

CACHE_FORMAT_VERSION = 2


@dataclass(frozen=True)
class CustomDomain:
    """A structured Cloudsmith custom domain record."""

    host: str
    backend_kind: int | None
    enabled: bool
    validated: bool
    org: str
    domain_type: DomainType
    repository: str | None = None
    primary: bool = True
    created_at: str | None = None

    @property
    def is_active(self) -> bool:
        """Whether this domain can serve traffic at all."""
        return self.enabled and self.validated

    def serves_repository(self, repository: str | None) -> bool:
        """Whether this domain may be used for `repository`."""
        return not self.repository or self.repository == repository


def get_cache_dir() -> Path:
    """
    Get the cache directory for custom domains, creating it where possible.

    A directory that cannot be created is not an error: every read path then
    resolves to a miss, and :func:`write_cache` already degrades on ``OSError``.
    """
    cache_dir = Path(get_default_config_path()) / "custom_domains_cache"
    try:
        cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        logger.debug("Could not create cache directory %s: %s", cache_dir, exc)
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
    """Read a repository slug: the API nests it, the cache stores it flat."""
    if isinstance(raw, dict):
        raw = raw.get("slug")
    return raw or None


def _timestamp(raw) -> str | None:
    """Read a creation time as a string: the SDK gives a datetime, the cache a str.

    ``json.dump`` cannot write a datetime, so it is normalised on the way in
    rather than at every cache write.
    """
    if raw is None or isinstance(raw, str):
        return raw or None
    return raw.isoformat()


def _record_from_payload(raw: dict, org: str) -> CustomDomain:
    """Build a CustomDomain from an API or cache payload for *org*."""
    backend_kind = raw.get("backend_kind")
    return CustomDomain(
        host=raw["host"],
        backend_kind=backend_kind,
        enabled=bool(raw.get("enabled")),
        validated=bool(raw.get("validated")),
        org=org,
        repository=_repository_slug(raw.get("repository")),
        domain_type=domain_type_from_server(raw.get("domain_type")),
        primary=bool(raw.get("primary")),
        created_at=_timestamp(raw.get("created_at")),
    )


def _precedence_key(domain: CustomDomain, repository: str | None) -> tuple:
    """Rank a candidate domain, lowest first.

    A domain bound to *repository* beats an organisation-wide one, primary
    beats secondary, the oldest wins, and the host breaks any remaining tie. A
    record with no ``created_at`` sorts after every dated one.
    """
    bound_to_repository = repository is not None and domain.repository == repository
    return (
        not bound_to_repository,
        not domain.primary,
        domain.created_at is None,
        domain.created_at or "",
        domain.host,
    )


def order_by_precedence(
    domains: list[CustomDomain], repository: str | None = None
) -> list[CustomDomain]:
    """Return *domains* ranked as Cloudsmith would choose among them.

    The first entry is the one that serves *repository*, so a caller listing
    candidates shows the same answer the credential path would bind.
    """
    return sorted(domains, key=lambda domain: _precedence_key(domain, repository))


def read_cache(cache_path: Path) -> list[CustomDomain] | None:
    """Return the cached custom domains at `cache_path`, or None for a miss.

    ``format_version`` is what separates a document this CLI can read from one
    an older build wrote, so anything failing that check needs no further
    handling of its shape - including the versionless documents that stored
    domains as plain strings.
    """
    if not is_cache_valid(cache_path):
        return None

    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.debug("Failed to read cache %s: %s", cache_path, exc)
        return None

    if not isinstance(data, dict) or data.get("format_version") != CACHE_FORMAT_VERSION:
        logger.debug(
            "Cache %s is not format version %s - treating as miss",
            cache_path,
            CACHE_FORMAT_VERSION,
        )
        return None

    domains = data.get("domains")
    if not isinstance(domains, list):
        return None

    records = [
        _record_from_payload(d, d.get("org", ""))
        for d in domains
        if isinstance(d, dict) and d.get("host")
    ]
    logger.debug("Read %d domains from cache: %s", len(records), cache_path)
    return records


def read_all_cached_domains() -> list[CustomDomain]:
    """Return every custom domain in a currently-valid cache entry.

    Lets a run with no configured organisation list what earlier runs already
    fetched, at no API cost.  Each file goes through :func:`read_cache`, so the
    TTL and format-version gates apply and a stale or unreadable entry is
    skipped rather than reported.
    """
    records: list[CustomDomain] = []
    for cache_path in sorted(get_cache_dir().glob("*.json")):
        cached = read_cache(cache_path)
        if cached:
            records.extend(cached)
    return records


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
                "domain_type": d.domain_type.value,
                "primary": d.primary,
                "created_at": d.created_at,
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


def get_custom_domains(
    org: str,
    *,
    credential: CredentialResult | None = None,
    api_host: str | None = None,
    refresh: bool = False,
    strict: bool = False,
    configure_api: bool = True,
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
            instead of degrading to an empty list. Use it for callers that show
            results to a user, which must not render a typo'd org, a missing
            permission or an unreachable API as "no custom domains". No failure
            is ever cached, so a strict lookup can still be served from the
            cache.
        configure_api: When ``True`` (default), configure the SDK from
            ``api_host`` and ``credential``. Pass ``False`` when the caller has
            already done so, since the CLI's ``initialise_api`` also carries
            proxy, TLS-verification, user-agent and header settings that this
            narrower configuration would discard.

    Returns:
        List of CustomDomain records. Empty if the org has no custom domains,
        which the API answers as 200 with an empty array and is cached like any
        other result, or if the call fails and ``strict`` is False.

    Note:
        The API layer wraps transport failures (DNS/timeout/SSL) into
        ``ApiException``, so every failure mode lands in the handler below.
        Helpers degrade rather than break the tool wrapping them; pass
        ``strict=True`` to fail loudly instead.
    """
    cache_path = get_cache_path(org)
    cached = None if refresh else read_cache(cache_path)
    if cached is not None:
        logger.debug("Using cached custom domains for %s", org)
        return cached

    logger.debug("Fetching custom domains from API for %s", org)

    from ..core.api.exceptions import ApiException
    from ..core.api.init import initialise_api
    from ..core.api.orgs import list_custom_domains

    if configure_api:
        initialise_api(host=api_host, credential=credential)

    try:
        raw_domains = list_custom_domains(org)
    except ApiException as exc:
        if strict:
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
    configure_api: bool = True,
) -> list[str]:
    """
    Return enabled and validated custom domain hostnames for a specific backend format.

    Args:
        org: Organization slug
        backend_kind: BackendKind int value (e.g. BackendKind.DOCKER == 6)
        credential: Optional resolved credential for authentication
        api_host: Cloudsmith API host URL
        refresh: When ``True``, bypass the cache and fetch fresh data from the API.
        configure_api: When ``True`` (default), configure the SDK from
            ``api_host`` and ``credential``. Pass ``False`` when the caller has
            already done so, for the reasons :func:`get_custom_domains` gives.

    Returns:
        Hostnames that are usable and match the given backend_kind, in
        precedence order - the host Cloudsmith would treat as active first.
    """
    domains = get_custom_domains(
        org,
        credential=credential,
        api_host=api_host,
        refresh=refresh,
        configure_api=configure_api,
    )
    matching = [
        domain
        for domain in domains
        if domain.backend_kind == int(backend_kind) and domain.is_active
    ]
    matching.sort(key=lambda domain: _precedence_key(domain, None))
    return [domain.host for domain in matching]
