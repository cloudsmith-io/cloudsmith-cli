# -*- coding: utf-8 -*-
"""API - User endpoints."""
from __future__ import absolute_import, print_function, unicode_literals

import cloudsmith_api

from .. import ratelimits
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
        data, _, headers = client.user_token_create_with_http_info(
            data={"email": login, "password": password}
        )

    ratelimits.maybe_rate_limit(client, headers)
    return data.token


def get_user_brief():
    """Retrieve brief for current user (if any)."""
    client = get_user_api()

    with catch_raise_api_exception():
        data, _, headers = client.user_self_with_http_info()

    ratelimits.maybe_rate_limit(client, headers)
    return data.authenticated, data.slug, data.email, data.name
