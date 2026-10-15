# Copyright 2026 Cloudsmith Ltd
"""
Helper for discovering the domains that serve a Cloudsmith Workspace.

The v2 API lists both the Cloudsmith-owned domains and a Workspace's own custom
domains, already in preference order. The CLI therefore holds no table of
Cloudsmith hostnames: whichever API host it is configured for supplies its own.

Results are cached on the filesystem, one directory per API host, so that a
Workspace slug on one Cloudsmith never answers for the same slug on another.
Domains change rarely, so the cache is long-lived and ``--refresh`` bypasses
it when one has just been added or validated. The cache keeps the server's
records as sent; bump ``CACHE_FORMAT_VERSION`` when that shape changes.
"""

import hashlib
import json
import logging
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

from ..cli.config import get_default_config_path
from ..core.cache_utils import atomic_write_json
from ..core.credentials.models import CredentialContext, CredentialResult
from .backends import BackendKind

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 7 * 24 * 3600

CACHE_FORMAT_VERSION = 3

NATIVE_TYPE_PREFIX = "NATIVE_"

SERVER_FORMAT_NAMES = {"HELM_OCI": "HELM"}


class DomainType(str, Enum):
    """What a Cloudsmith host is for.

    A host that serves a single package format speaks that format's native
    protocol (``NATIVE_API``); the format-less hosts are the download CDN, the
    generic upload endpoint and the Cloudsmith API itself.
    """

    DOWNLOAD = "download"
    UPLOAD = "upload"
    CLOUDSMITH_API = "cloudsmith_api"
    NATIVE_API = "native_api"


class DomainScope(str, Enum):
    """Whom a domain serves: every Workspace, one Workspace, or one repository."""

    GLOBAL = "global"
    WORKSPACE = "workspace"
    REPOSITORY = "repository"


def format_for_backend_kind(backend_kind: int | None) -> str | None:
    """Return the package format a backend kind serves, or None.

    A host with no backend kind serves no single format and resolves to
    ``None``. :class:`BackendKind` is hand-maintained, so a format the CLI does
    not know yet renders as ``unknown`` rather than breaking its caller.
    """
    if backend_kind is None:
        return None

    try:
        return BackendKind(backend_kind).name.lower()
    except ValueError:
        return "unknown"


@dataclass(frozen=True)
class WorkspaceDomain:
    """A domain that serves a Workspace, as the server reported it."""

    host: str
    domain_type: DomainType
    backend_kind: int | None
    scope: DomainScope
    workspace: str | None
    repository: str | None = None

    @property
    def is_custom(self) -> bool:
        """Whether a Workspace owns this domain, rather than Cloudsmith."""
        return self.scope is not DomainScope.GLOBAL

    @property
    def format_label(self) -> str | None:
        """The package format this host serves, or None for no single format."""
        return format_for_backend_kind(self.backend_kind)

    def serves_repository(self, repository: str | None) -> bool:
        """Whether this domain may be used for `repository`."""
        return not self.repository or self.repository == repository


def _classify(server_type) -> tuple[DomainType, int | None] | None:
    """Return the purpose and format a server domain type names, or None.

    The server adds domain types over time. A type this CLI does not know has
    no safe reading, so it resolves to None and the caller skips the domain.
    """
    if not isinstance(server_type, str):
        return None

    if server_type.startswith(NATIVE_TYPE_PREFIX):
        name = server_type.removeprefix(NATIVE_TYPE_PREFIX)
        backend_kind = BackendKind.__members__.get(SERVER_FORMAT_NAMES.get(name, name))
        if backend_kind is None:
            return None
        return DomainType.NATIVE_API, int(backend_kind)

    try:
        return DomainType(server_type.lower()), None
    except ValueError:
        return None


def _scope(server_scope) -> DomainScope | None:
    try:
        return DomainScope(str(server_scope).lower())
    except ValueError:
        return None


def domain_from_payload(raw: dict, workspace: str) -> WorkspaceDomain | None:
    """Build a WorkspaceDomain from one v2 API record, or None to skip it."""
    classified = _classify(raw.get("domain_type"))
    scope = _scope(raw.get("domain_scope"))
    if classified is None or scope is None or not raw.get("domain_name"):
        logger.debug("Skipping domain record %r", raw)
        return None

    domain_type, backend_kind = classified
    return WorkspaceDomain(
        host=raw["domain_name"],
        domain_type=domain_type,
        backend_kind=backend_kind,
        scope=scope,
        workspace=None if scope is DomainScope.GLOBAL else workspace,
        repository=raw.get("repository") or None,
    )


def _domains_from_payload(payload: list, workspace: str) -> list[WorkspaceDomain]:
    return [
        domain
        for raw in payload
        if isinstance(raw, dict)
        and (domain := domain_from_payload(raw, workspace)) is not None
    ]


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def _default_api_host() -> str:
    """Return the API host that the SDK calls when no host is given.

    The SDK is read only if it is already loaded, so a cache hit does not
    import it.
    """
    sdk = sys.modules.get("cloudsmith_api")
    return sdk.Configuration().host if sdk else CredentialContext.api_host


def _cache_dir_name(api_host: str | None) -> str:
    """Name the cache directory after the complete API base URL.

    The scheme, port and path are part of the name, so two Cloudsmith
    deployments on one hostname never share a cache.
    """
    api_base = (api_host or _default_api_host()).rstrip("/")
    digest = hashlib.sha256(api_base.encode("utf-8")).hexdigest()[:16]
    return f"{_safe_name(urlparse(api_base).hostname or 'default')}-{digest}"


def get_cache_dir(api_host: str | None = None) -> Path:
    """
    Get the domain cache directory for an API host, creating it where possible.

    ``None`` names the SDK's default API host. A directory that cannot be
    created is not an error: every read path then resolves to a miss, and
    :func:`write_cache` already degrades on ``OSError``.
    """
    cache_dir = (
        Path(get_default_config_path()) / "domains_cache" / _cache_dir_name(api_host)
    )
    try:
        cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        logger.debug("Could not create cache directory %s: %s", cache_dir, exc)
    return cache_dir


def get_cache_path(workspace: str, api_host: str | None = None) -> Path:
    """Get the cache file path for a Workspace's domains on an API host."""
    return get_cache_dir(api_host) / f"{_safe_name(workspace)}.json"


def is_cache_valid(cache_path: Path) -> bool:
    """Check if a cache file exists and has not expired."""
    if not cache_path.exists():
        return False

    try:
        mtime = cache_path.stat().st_mtime
        age = time.time() - mtime
        return age < CACHE_TTL_SECONDS
    except OSError:
        return False


def read_cache(cache_path: Path) -> list[WorkspaceDomain] | None:
    """Return the cached domains at `cache_path`, or None for a miss.

    ``format_version`` is what separates a document this CLI can read from one
    an older build wrote, so anything failing that check needs no further
    handling of its shape.
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

    records = _domains_from_payload(domains, data.get("workspace", ""))
    logger.debug("Read %d domains from cache: %s", len(records), cache_path)
    return records


def read_all_cached_domains(api_host: str | None = None) -> list[WorkspaceDomain]:
    """Return every domain in a currently-valid cache entry for an API host.

    Lets a run with no configured Workspace list what earlier runs already
    fetched, at no API cost. Each file goes through :func:`read_cache`, so the
    TTL and format-version gates apply and a stale or unreadable entry is
    skipped rather than reported.
    """
    records: list[WorkspaceDomain] = []
    for cache_path in sorted(get_cache_dir(api_host).glob("*.json")):
        cached = read_cache(cache_path)
        if cached:
            records.extend(cached)
    return records


def write_cache(cache_path: Path, workspace: str, payload: list[dict]) -> None:
    """Write a Workspace's domain records, as the server sent them, to the cache."""
    data = {
        "format_version": CACHE_FORMAT_VERSION,
        "workspace": workspace,
        "domains": payload,
        "cached_at": time.time(),
    }
    try:
        atomic_write_json(cache_path, data)
        logger.debug("Wrote %d domains to cache: %s", len(payload), cache_path)
    except OSError as exc:
        logger.debug("Failed to write cache %s: %s", cache_path, exc)


def get_workspace_domains(
    workspace: str,
    *,
    credential: CredentialResult | None = None,
    api_host: str | None = None,
    refresh: bool = False,
    strict: bool = False,
    configure_api: bool = True,
) -> list[WorkspaceDomain]:
    """
    Fetch the domains that serve a Cloudsmith Workspace, most-preferred first.

    Results are cached on the filesystem for 7 days to avoid excessive API calls.

    Args:
        workspace: Workspace slug
        credential: Optional resolved credential for authentication; it carries
            its own auth scheme (X-Api-Key vs Authorization: Bearer)
        api_host: Cloudsmith API host URL. Taken from the SDK configuration
            default when not provided.
        refresh: When ``True``, skip the cache read and always fetch from the API.
            The fresh result is still written to the cache.
        strict: When ``True``, a failed lookup re-raises its ``ApiException``
            instead of degrading to an empty list. Use it for callers that show
            results to a user, which must not render a typo'd Workspace, a
            missing permission or an unreachable API as "no domains". No
            failure is ever cached, so a strict lookup can still be served from
            the cache.
        configure_api: When ``True`` (default), configure the SDK from
            ``api_host`` and ``credential``. Pass ``False`` when the caller has
            already done so, since the CLI's ``initialise_api`` also carries
            proxy, TLS-verification, user-agent and header settings that this
            narrower configuration would discard.

    Returns:
        List of WorkspaceDomain records in the server's preference order:
        repository domains, then Workspace domains, then Cloudsmith-owned
        domains. Empty if the call fails and ``strict`` is False.

    Note:
        The API layer wraps transport failures (DNS/timeout/SSL) into
        ``ApiException``, so every failure mode lands in the handler below.
        Helpers degrade rather than break the tool wrapping them; pass
        ``strict=True`` to fail loudly instead.
    """
    cache_path = get_cache_path(workspace, api_host)
    cached = None if refresh else read_cache(cache_path)
    if cached is not None:
        logger.debug("Using cached domains for %s", workspace)
        return cached

    logger.debug("Fetching domains from API for %s", workspace)

    from ..core.api.exceptions import ApiException
    from ..core.api.init import initialise_api
    from ..core.api.workspaces import list_domains

    if configure_api:
        initialise_api(host=api_host, credential=credential)

    try:
        payload = list_domains(workspace, credential=credential)
    except ApiException as exc:
        if strict:
            raise
        logger.debug("Failed to fetch domains for %s: HTTP %s", workspace, exc.status)
        return []

    records = _domains_from_payload(payload, workspace)

    logger.debug("Fetched %d domains for %s", len(records), workspace)
    write_cache(cache_path, workspace, payload)
    return records


def get_format_domains(
    workspace: str,
    backend_kind: int,
    *,
    credential: CredentialResult | None = None,
    api_host: str | None = None,
    refresh: bool = False,
    configure_api: bool = True,
) -> list[str]:
    """
    Return the hostnames that serve a package format for a Workspace.

    Args:
        workspace: Workspace slug
        backend_kind: BackendKind int value (e.g. BackendKind.DOCKER == 6)
        credential: Optional resolved credential for authentication
        api_host: Cloudsmith API host URL
        refresh: When ``True``, bypass the cache and fetch fresh data from the API.
        configure_api: When ``True`` (default), configure the SDK from
            ``api_host`` and ``credential``. Pass ``False`` when the caller has
            already done so, for the reasons :func:`get_workspace_domains` gives.

    Returns:
        Hostnames that speak the given format's native protocol, in the
        server's preference order. Cloudsmith-owned hosts come last.
    """
    domains = get_workspace_domains(
        workspace,
        credential=credential,
        api_host=api_host,
        refresh=refresh,
        configure_api=configure_api,
    )
    return [
        domain.host for domain in domains if domain.backend_kind == int(backend_kind)
    ]
