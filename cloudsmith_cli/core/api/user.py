"""API - User endpoints."""

import json

import cloudsmith_api
from cloudsmith_api.rest import ApiException

from .. import ratelimits
from .exceptions import TwoFactorRequiredException, catch_raise_api_exception
from .init import get_api_client, unset_api_key


def get_user_api():
    """Get the user API client."""
    return get_api_client(cloudsmith_api.UserApi)


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

    try:
        data, _, headers = client.user_token_create_with_http_info(data=data_dict)
        ratelimits.maybe_rate_limit(client, headers)
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
