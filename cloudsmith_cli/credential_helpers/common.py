# Copyright 2026 Cloudsmith Ltd
"""
Shared utilities for credential helpers.

Provides domain checking used by all credential helpers.
"""

import logging
import os

from .custom_domains import get_custom_domains, get_format_domains

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


def is_cloudsmith_domain(
    url, api_key=None, auth_type="api_key", api_host=None, backend_kind=None
):
    """
    Check if a URL points to a Cloudsmith service.

    Checks standard *.cloudsmith.io domains first (no auth needed).
    If not a standard domain, queries the Cloudsmith API for custom domains.

    Args:
        url: URL or hostname to check
        api_key: API key/token for authenticating custom domain lookups
        auth_type: "api_key" (X-Api-Key header) or "bearer" (Authorization: Bearer)
        api_host: Cloudsmith API host URL
        backend_kind: If given, custom domains only match when their backend_kind
            equals it (standard *.cloudsmith.io domains always match regardless).
            When None (default), any enabled+validated custom domain matches.

    Returns:
        bool: True if this is a Cloudsmith domain
    """
    hostname = extract_hostname(url)
    if not hostname:
        return False

    # Standard Cloudsmith domains — no auth needed, always match regardless of backend_kind
    if (
        hostname in ("cloudsmith.io", "cloudsmith.com")
        or hostname.endswith(".cloudsmith.io")
        or hostname.endswith(".cloudsmith.com")
    ):
        return True

    # Custom domains require org + auth
    org = os.environ.get("CLOUDSMITH_ORG", "").strip()
    if not org:
        return False

    if not api_key:
        return False

    if backend_kind is not None:
        hosts = {
            host.lower()
            for host in get_format_domains(
                org,
                backend_kind,
                api_key=api_key,
                auth_type=auth_type,
                api_host=api_host,
            )
        }
    else:
        hosts = {
            d.host.lower()
            for d in get_custom_domains(
                org, api_key=api_key, auth_type=auth_type, api_host=api_host
            )
            if d.enabled and d.validated
        }
    return hostname in hosts
