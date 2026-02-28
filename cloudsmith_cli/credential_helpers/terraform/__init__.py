"""
Terraform credential helper logic for Cloudsmith.

This module provides functions for retrieving credentials for Terraform registries
using the existing Cloudsmith credential provider chain (OIDC, API keys, config, keyring).
"""

import os

from ..common import extract_hostname, is_cloudsmith_domain, resolve_credentials


def get_credentials(hostname, debug=False):
    """
    Get a token for a Cloudsmith Terraform registry.

    Checks whether the hostname is a Cloudsmith domain before attempting
    credential resolution, so non-Cloudsmith registries (e.g.
    registry.terraform.io) are skipped silently.

    Terraform expects tokens in the format:
    - Standard domains: org/repo/token
    - Custom domains: repo/token (org is implicit in the domain)

    Args:
        hostname: The registry hostname
        debug: Enable debug logging

    Returns:
        str: Token in format "org/repo/token" or "repo/token", or None
    """
    bare_hostname = extract_hostname(hostname)
    is_standard = bare_hostname and (
        bare_hostname.endswith("cloudsmith.io") or bare_hostname == "cloudsmith.io"
    )

    if not is_standard:
        return _get_custom_domain_credentials(hostname, debug)

    return _get_standard_domain_credentials(debug)


def _get_custom_domain_credentials(hostname, debug):
    """Get credentials for a custom (non-cloudsmith.io) domain."""
    org = os.environ.get("CLOUDSMITH_ORG", "").strip()
    if not org:
        return None

    result = resolve_credentials(debug)
    if not result:
        return None

    if not is_cloudsmith_domain(hostname, _credential_result=result):
        return None

    repo = os.environ.get("CLOUDSMITH_REPO", "").strip()
    if not repo:
        return None
    return f"{repo}/{result.api_key}"


def _get_standard_domain_credentials(debug):
    """Get credentials for a standard cloudsmith.io domain."""
    result = resolve_credentials(debug)
    if not result:
        return None

    org = os.environ.get("CLOUDSMITH_ORG", "").strip()
    repo = os.environ.get("CLOUDSMITH_REPO", "").strip()

    if not org or not repo:
        return None

    return f"{org}/{repo}/{result.api_key}"
