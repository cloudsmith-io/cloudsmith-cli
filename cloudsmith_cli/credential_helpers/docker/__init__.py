"""
Docker credential helper logic for Cloudsmith.

This module provides functions for retrieving credentials for Docker registries
using the existing Cloudsmith credential provider chain (OIDC, API keys, config, keyring).
"""

from ..common import is_cloudsmith_domain, resolve_credentials


def get_credentials(server_url, debug=False):
    """
    Get credentials for a Cloudsmith Docker registry.

    Resolves credentials first, then verifies the URL is a Cloudsmith registry
    (including custom domains, authenticated via the resolved token).

    Args:
        server_url: The Docker registry server URL
        debug: Enable debug logging

    Returns:
        dict: Credentials with 'Username' and 'Secret' keys, or None
    """
    result = resolve_credentials(debug)
    if not result:
        return None

    if not is_cloudsmith_domain(server_url, _credential_result=result):
        return None

    return {"Username": "token", "Secret": result.api_key}
