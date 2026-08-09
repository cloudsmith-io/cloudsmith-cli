# Copyright 2026 Cloudsmith Ltd
"""
Shared utilities for credential helpers.

Provides domain checking used by all credential helpers.
"""

import logging

from .custom_domains import get_custom_domains, get_format_domains
from .default_domains import load_default_domains

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
    normalized = normalized.removeprefix("sparse+")

    # Remove protocol
    if "://" in normalized:
        normalized = normalized.split("://", 1)[1]

    # Remove userinfo (user@host)
    if "@" in normalized.split("/")[0]:
        normalized = normalized.split("@", 1)[1]

    # Extract hostname (before first / or :)
    hostname = normalized.split("/")[0].split(":")[0]

    return hostname


def is_standard_cloudsmith_host(url):
    """Return True if *url*'s host is a standard Cloudsmith host.

    Standard hosts are ``cloudsmith.io``/``cloudsmith.com`` and their
    subdomains.  Anything else is treated as a custom domain.
    """
    hostname = extract_hostname(url)
    return hostname in ("cloudsmith.io", "cloudsmith.com") or hostname.endswith(
        (".cloudsmith.io", ".cloudsmith.com")
    )


def is_default_host(url):
    """Return True if *url*'s host is one of the effective default hosts.

    The effective table is the built-in ``*.cloudsmith.io`` hosts, replaced
    wholesale by a trusted ``[domains]`` override when a deployment declares
    one.  Either way, a match here is the deployment's own service host - the
    equivalent of ``dl.cloudsmith.io`` - not a genuinely discovered custom
    domain.
    """
    hostname = extract_hostname(url)
    return any(domain.host.lower() == hostname for domain in load_default_domains())


def repo_path_segment(owner, repo, host):
    """Return the path segment identifying the repository in a Cloudsmith URL.

    A default host - built-in or declared in a trusted ``[domains]`` table -
    includes the org (``<owner>/<repo>``), the same as any standard
    ``*.cloudsmith.io`` host.  A discovered custom domain is bound to a single
    org, so the org is omitted (``<repo>``).  This rule is Cloudsmith-wide,
    not format-specific.
    """
    if is_standard_cloudsmith_host(host) or is_default_host(host):
        return f"{owner}/{repo}"
    return repo


def is_cloudsmith_domain(
    url, credential=None, api_host=None, backend_kind=None, org=None
):
    """
    Check if a URL points to a Cloudsmith service.

    Checks standard *.cloudsmith.io domains first (no auth needed).
    If not a standard domain, queries the Cloudsmith API for custom domains.

    Args:
        url: URL or hostname to check
        credential: Resolved CredentialResult for authenticating custom domain lookups
        api_host: Cloudsmith API host URL
        backend_kind: If given, custom domains only match when their backend_kind
            equals it (standard *.cloudsmith.io domains always match regardless).
            When None (default), any enabled+validated custom domain matches.
        org: Organisation slug whose custom domains to match against, as the
            CLI resolved it from --org, CLOUDSMITH_ORG or config.ini

    Returns:
        bool: True if this is a Cloudsmith domain
    """
    hostname = extract_hostname(url)
    if not hostname:
        return False

    # Standard Cloudsmith domains — no auth needed, always match regardless of backend_kind
    if is_standard_cloudsmith_host(hostname):
        return True

    # Custom domains require org + auth
    if not org:
        return False

    if not credential or not credential.api_key:
        return False

    if backend_kind is not None:
        hosts = {
            host.lower()
            for host in get_format_domains(
                org,
                backend_kind,
                credential=credential,
                api_host=api_host,
            )
        }
    else:
        hosts = {
            d.host.lower()
            for d in get_custom_domains(org, credential=credential, api_host=api_host)
            if d.is_active
        }
    return hostname in hosts
