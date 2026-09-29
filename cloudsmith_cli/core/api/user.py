"""API - User endpoints."""

import cloudsmith_api

from .. import ratelimits
from .exceptions import catch_raise_api_exception
from .init import get_api_client


def get_user_api():
    """Get the user API client."""
    return get_api_client(cloudsmith_api.UserApi)


def create_user_token_saml() -> dict:
    """Create a new user API token using SAML."""
    client = get_user_api()

    with catch_raise_api_exception():
        data, _, headers = client.user_tokens_create_with_http_info()

    ratelimits.maybe_rate_limit(client, headers)
    return data


def get_user_brief():
    """Retrieve brief for current user (if any)."""
    client = get_user_api()

    with catch_raise_api_exception():
        data, _, headers = client.user_self_with_http_info()

    ratelimits.maybe_rate_limit(client, headers)
    return data.authenticated, data.slug, data.email, data.name


def list_user_tokens() -> list[dict]:
    """List all user API tokens."""
    client = get_user_api()

    with catch_raise_api_exception():
        data, _, headers = client.user_tokens_list_with_http_info()

    ratelimits.maybe_rate_limit(client, headers)
    return data.results


def refresh_user_token(token_slug: str) -> dict:
    """Refresh user API token."""
    client = get_user_api()

    with catch_raise_api_exception():
        data, _, headers = client.user_tokens_refresh_with_http_info(token_slug)

    ratelimits.maybe_rate_limit(client, headers)
    return data


def get_token_metadata() -> dict | None:
    """Retrieve metadata for the user's first API token.

    Raises ApiException on failure; callers should handle gracefully.
    """
    if t := next(iter(list_user_tokens()), None):
        return {"slug": t.slug_perm, "created": t.created}
    return None
