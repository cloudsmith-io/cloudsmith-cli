"""API - User endpoints."""

import json

import cloudsmith_sdk
from cloudsmith_api.rest import ApiException
from cloudsmith_sdk.models import UserAuthTokenRequest

from .exceptions import TwoFactorRequiredException, catch_raise_api_exception
from .init import get_new_api_client, unset_api_key


def get_user_api() -> cloudsmith_sdk.UserApi:
    """Get the user API client."""
    return get_new_api_client().user


def get_user_token(login, password, totp_token=None, two_factor_token=None):
    """Retrieve user token from the API (via authentication)."""
    client = get_user_api()

    # Never use API key for the token endpoint
    unset_api_key()

    # Prepare data based on whether this is initial login or 2FA completion
    if totp_token and two_factor_token:
        data_dict = {
            "totp_token": totp_token,
            "two_factor_token": two_factor_token,
        }
    else:
        data_dict = {
            "email": login,
            "password": password,
        }

    token_create_request = UserAuthTokenRequest.from_dict(data_dict)

    try:
        data = client.token_create(body=token_create_request)
        return data.token
    except ApiException as e:
        # Check for 2FA requirement
        if e.status == 422 and e.body:
            try:
                response_data = json.loads(e.body)
                if response_data.get("two_factor_required"):
                    two_factor_token = response_data.get("two_factor_token")
                    # Raise custom exception for 2FA requirement
                    raise TwoFactorRequiredException(two_factor_token)
            except (ValueError, KeyError):
                pass

        # If not 2FA, use the context manager to handle other API exceptions
        with catch_raise_api_exception():
            raise


def create_user_token_saml() -> dict:
    """Create a new user API token using SAML."""
    client = get_user_api()

    with catch_raise_api_exception():
        data = client.tokens_create()

    return data


def get_user_brief():
    """Retrieve brief for current user (if any)."""
    client = get_user_api()

    with catch_raise_api_exception():
        data = client.self()

    return data.authenticated, data.slug, data.email, data.name


def list_user_tokens() -> list[dict]:
    """List all user API tokens."""
    client = get_user_api()

    with catch_raise_api_exception():
        return list(client.tokens_list())


def refresh_user_token(token_slug: str) -> dict:
    """Refresh user API token."""
    client = get_user_api()

    with catch_raise_api_exception():
        return client.tokens_refresh(token_slug)


def get_token_metadata() -> dict | None:
    """Retrieve metadata for the user's first API token.

    Raises ApiException on failure; callers should handle gracefully.
    """
    if t := next(iter(list_user_tokens()), None):
        return {"slug": t.slug_perm, "created": t.created}
    return None
