"""API - User endpoints."""
from __future__ import absolute_import, print_function, unicode_literals

import cloudsmith_api

from .exceptions import catch_raise_api_exception
from .init import get_api_client, set_api_key


def get_user_api():
    """Get the user API client."""
    return get_api_client(cloudsmith_api.UserApi)


def get_user_token(login, password):
    """Retrieve user token from the API (via authentication)."""
    client = get_user_api()

    # Never use API key for the token endpoint
    config = cloudsmith_api.Configuration()
    set_api_key(config, None)

    with catch_raise_api_exception():
        data = client.user_token_create(
            data={
                'email': login,
                'password': password
            }
        )

    return data.token


def get_user_brief():
    """Retrieve brief for current user (if any)."""
    client = get_user_api()

    with catch_raise_api_exception():
        data = client.user_self()

    return data.authenticated, data.slug, data.email, data.name
