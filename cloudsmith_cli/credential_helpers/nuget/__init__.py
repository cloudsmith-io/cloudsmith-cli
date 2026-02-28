"""
NuGet credential provider logic for Cloudsmith.

This module provides functions for retrieving credentials for NuGet feeds
using the existing Cloudsmith credential provider chain (OIDC, API keys, config, keyring).
"""

from ..common import is_cloudsmith_domain, resolve_credentials


def get_credentials(uri, debug=False):
    """
    Get credentials for a Cloudsmith NuGet feed.

    Resolves credentials first, then verifies the URI is a Cloudsmith feed
    (including custom domains, authenticated via the resolved token).

    Args:
        uri: The NuGet package source URI
        debug: Enable debug logging

    Returns:
        dict: Credentials with 'Username' and 'Password' keys, or None
    """
    result = resolve_credentials(debug)
    if not result:
        return None

    if not is_cloudsmith_domain(uri, _credential_result=result):
        return None

    return {"Username": "token", "Password": result.api_key}
