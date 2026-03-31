"""
Docker credential helper logic for Cloudsmith.

This module provides functions for retrieving credentials for Docker registries
using the existing Cloudsmith credential provider chain (OIDC, API keys, config, keyring).
"""

from ..common import is_cloudsmith_domain


def get_credentials(server_url, credential=None, session=None, api_host=None):
    """
    Get credentials for a Cloudsmith Docker registry.

    Verifies the URL is a Cloudsmith registry (including custom domains)
    and returns credentials if available.

    Args:
        server_url: The Docker registry server URL
        credential: Pre-resolved CredentialResult from the provider chain
        session: Pre-configured requests.Session with proxy/SSL settings
        api_host: Cloudsmith API host URL

    Returns:
        dict: Credentials with 'Username' and 'Secret' keys, or None
    """
    if not credential or not credential.api_key:
        return None

    if not is_cloudsmith_domain(
        server_url,
        session=session,
        api_key=credential.api_key,
        api_host=api_host,
    ):
        return None

    return {"Username": "token", "Secret": credential.api_key}
