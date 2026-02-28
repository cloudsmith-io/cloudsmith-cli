"""
Helper for discovering Cloudsmith custom domains.

This module provides functions to fetch custom domains from the Cloudsmith API
for use in credential helpers. Results are cached on the filesystem.
"""

import json
import logging
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Cache custom domains for 1 hour
CACHE_TTL_SECONDS = 3600


def get_cache_dir() -> Path:
    """
    Get the cache directory for custom domains.

    Returns:
        Path to cache directory (e.g., ~/.cloudsmith/cache/custom_domains/)
    """
    home = Path.home()
    cache_dir = home / ".cloudsmith" / "cache" / "custom_domains"
    cache_dir.mkdir(parents=True, exist_ok=True)
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


def read_cache(cache_path: Path) -> Optional[List[str]]:
    """
    Read custom domains from cache file.

    Args:
        cache_path: Path to cache file

    Returns:
        List of domain strings or None if cache invalid/missing
    """
    if not is_cache_valid(cache_path):
        return None

    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "domains" in data:
                domains = data["domains"]
                if isinstance(domains, list):
                    logger.debug(
                        "Read %d domains from cache: %s", len(domains), cache_path
                    )
                    return domains
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Failed to read cache %s: %s", cache_path, exc)

    return None


def write_cache(cache_path: Path, domains: List[str]) -> None:
    """
    Write custom domains to cache file.

    Args:
        cache_path: Path to cache file
        domains: List of domain strings to cache
    """
    try:
        data = {
            "domains": domains,
            "cached_at": time.time(),
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        logger.debug("Wrote %d domains to cache: %s", len(domains), cache_path)
    except OSError as exc:
        logger.debug("Failed to write cache %s: %s", cache_path, exc)


def _create_session(
    api_key: str = None,
    proxy: str = None,
    ssl_verify: bool = True,
    user_agent: str = None,
    headers: dict = None,
):
    """Create a requests session with networking and auth configuration.

    Mirrors the pattern used by EnvironmentDetector._create_session() and
    exchange.create_exchange_session() so that custom-domain API calls
    respect the same proxy / TLS / header settings as the rest of the CLI.

    Args:
        api_key: Optional API key for Bearer auth.
        proxy: HTTP/HTTPS proxy URL.
        ssl_verify: Whether to verify SSL certificates.
        user_agent: Custom User-Agent string.
        headers: Additional headers to include.

    Returns:
        Configured requests.Session instance.
    """
    import requests

    session = requests.Session()

    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    session.verify = ssl_verify

    if user_agent:
        session.headers["User-Agent"] = user_agent

    if headers:
        session.headers.update(headers)

    if api_key:
        session.headers["Authorization"] = f"Bearer {api_key}"

    return session


def get_custom_domains_for_org(  # pylint: disable=too-many-return-statements
    org: str,
    api_host: str = "https://api.cloudsmith.io",
    api_key: str = None,
    proxy: str = None,
    ssl_verify: bool = True,
    user_agent: str = None,
    headers: dict = None,
) -> List[str]:
    """
    Fetch custom domains for a Cloudsmith organization.

    Results are cached on the filesystem for 1 hour to avoid excessive API calls.
    Networking settings (proxy, TLS, headers) are forwarded to the HTTP session
    so custom-domain lookups work behind proxies and with custom certificates.

    Args:
        org: Organization slug
        api_host: Cloudsmith API host
        api_key: Optional API key for authentication
        proxy: HTTP/HTTPS proxy URL
        ssl_verify: Whether to verify SSL certificates (default: True)
        user_agent: Custom User-Agent string
        headers: Additional headers to include

    Returns:
        List of custom domain strings (e.g., ['docker.customer.com', 'dl.customer.com'])
        Empty list if API call fails or org has no custom domains

    Example:
        >>> domains = get_custom_domains_for_org('my-org', api_key='token')
        >>> print(domains)
        ['docker.acme.com', 'dl.acme.com']
    """
    cache_path = get_cache_path(org)
    cached_domains = read_cache(cache_path)
    if cached_domains is not None:
        logger.debug("Using cached custom domains for %s", org)
        return cached_domains

    logger.debug("Fetching custom domains from API for %s", org)

    try:
        session = _create_session(
            api_key=api_key,
            proxy=proxy,
            ssl_verify=ssl_verify,
            user_agent=user_agent,
            headers=headers,
        )

        url = f"{api_host}/orgs/{org}/custom-domains/"

        response = session.get(url, timeout=10)

        if response.status_code in (401, 403):
            logger.debug(
                "Custom domains API requires auth - assuming no custom domains for %s",
                org,
            )
            return []  # Don't cache 401/403 - might work later with auth

        if response.status_code == 404:
            logger.debug("Organization %s not found or has no custom domains", org)
            write_cache(cache_path, [])  # Cache empty result to avoid repeated 404s
            return []

        if response.status_code != 200:
            logger.debug(
                "Failed to fetch custom domains for %s: HTTP %d",
                org,
                response.status_code,
            )
            return []

        data = response.json()

        # Expected format: [{"host": "docker.customer.com", ...}, ...]
        domains = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "host" in item:
                    domains.append(item["host"])

        logger.debug("Fetched %d custom domains for %s", len(domains), org)

        write_cache(cache_path, domains)

        return domains

    except ImportError:
        logger.debug("requests library not available, cannot fetch custom domains")
        return []
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("Error fetching custom domains: %s", exc)
        return []
