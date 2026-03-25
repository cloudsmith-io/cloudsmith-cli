"""
Shared utilities for credential helpers.

Provides domain checking used by all credential helpers.
"""

import logging
import os

logger = logging.getLogger(__name__)


def extract_hostname(url):
    """
    Extract bare hostname from any URL format.

    Handles protocols, sparse+ prefix, ports, paths, and trailing slashes.

    Args:
        url: URL in any format (e.g., "sparse+https://cargo.cloudsmith.io/org/repo/")

    Returns:
        str: Lowercase hostname (e.g., "cargo.cloudsmith.io")
    """
    if not url:
        return ""

    normalized = url.lower().strip()

    # Remove sparse+ prefix (Cargo)
    if normalized.startswith("sparse+"):
        normalized = normalized[7:]

    # Remove protocol
    if "://" in normalized:
        normalized = normalized.split("://", 1)[1]

    # Remove userinfo (user@host)
    if "@" in normalized.split("/")[0]:
        normalized = normalized.split("@", 1)[1]

    # Extract hostname (before first / or :)
    hostname = normalized.split("/")[0].split(":")[0]

    return hostname


def is_cloudsmith_domain(url, session=None, api_key=None, api_host=None):
    """
    Check if a URL points to a Cloudsmith service.

    Checks standard *.cloudsmith.io domains first (no auth needed).
    If not a standard domain, queries the Cloudsmith API for custom domains.

    Args:
        url: URL or hostname to check
        session: Pre-configured requests.Session with proxy/SSL settings
        api_key: API key for authenticating custom domain lookups
        api_host: Cloudsmith API host URL

    Returns:
        bool: True if this is a Cloudsmith domain
    """
    hostname = extract_hostname(url)
    if not hostname:
        return False

    # Standard Cloudsmith domains — no auth needed
    if hostname.endswith("cloudsmith.io") or hostname == "cloudsmith.io":
        return True

    # Custom domains require org + auth
    org = os.environ.get("CLOUDSMITH_ORG", "").strip()
    if not org:
        return False

    if not api_key:
        return False

    from .custom_domains import get_custom_domains_for_org

    custom_domains = get_custom_domains_for_org(
        org, session=session, api_key=api_key, api_host=api_host
    )

    return hostname in [d.lower() for d in custom_domains]
