"""
npm/pnpm token helper logic for Cloudsmith.

This module provides functions for retrieving tokens for npm/pnpm registries
using the existing Cloudsmith credential provider chain (OIDC, API keys, config, keyring).
"""

from ..common import resolve_credentials


def get_token(debug=False):
    """
    Get a Cloudsmith API token for npm/pnpm authentication.

    Returns the token string prefixed with "Bearer" for use with pnpm's tokenHelper.

    Args:
        debug: Enable debug logging

    Returns:
        str: "Bearer <token>" or None if not available
    """
    result = resolve_credentials(debug)
    if not result:
        return None

    return f"Bearer {result.api_key}"
