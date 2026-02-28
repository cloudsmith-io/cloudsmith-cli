"""
Cargo credential provider logic for Cloudsmith.

This module provides functions for retrieving credentials for Cargo registries
using the existing Cloudsmith credential provider chain (OIDC, API keys, config, keyring).
"""

from ..common import is_cloudsmith_domain, resolve_credentials


def get_credentials(index_url, debug=False):
    """
    Get a token for a Cloudsmith Cargo registry.

    Resolves credentials first, then verifies the URL is a Cloudsmith registry
    (including custom domains, authenticated via the resolved token).

    Args:
        index_url: The registry index URL (e.g., "sparse+https://cargo.cloudsmith.io/org/repo/")
        debug: Enable debug logging

    Returns:
        str: API token or None if not available
    """
    result = resolve_credentials(debug)
    if not result:
        return None

    if not is_cloudsmith_domain(index_url, _credential_result=result):
        return None

    return result.api_key
