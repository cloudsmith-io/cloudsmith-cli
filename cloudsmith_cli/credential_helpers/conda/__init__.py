"""
Conda auth handler logic for Cloudsmith.

This module provides functions for retrieving credentials for Conda channels
using the existing Cloudsmith credential provider chain (OIDC, API keys, config, keyring).
"""

from ..common import is_cloudsmith_domain, resolve_credentials


def get_credentials(url, debug=False):
    """
    Get credentials for a Cloudsmith Conda channel.

    Resolves credentials first, then verifies the URL is a Cloudsmith channel
    (including custom domains, authenticated via the resolved token).

    Args:
        url: The channel URL (e.g., "https://conda.cloudsmith.io/org/repo/")
        debug: Enable debug logging

    Returns:
        tuple: (username, token) or None if not available
    """
    result = resolve_credentials(debug)
    if not result:
        return None

    if not is_cloudsmith_domain(url, _credential_result=result):
        return None

    return ("token", result.api_key)
