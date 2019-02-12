# -*- coding: utf-8 -*-
"""API - Status endpoints."""
from __future__ import absolute_import, print_function, unicode_literals

import cloudsmith_api

from .. import ratelimits
from .exceptions import catch_raise_api_exception
from .init import get_api_client


def get_status_api():
    """Get the status API client."""
    return get_api_client(cloudsmith_api.StatusApi)


def get_status(with_version=False):
    """Retrieve status (and optionally) version from the API."""
    client = get_status_api()

    with catch_raise_api_exception():
        data, _, headers = client.status_check_basic_with_http_info()

    ratelimits.maybe_rate_limit(client, headers)

    if with_version:
        return data.detail, data.version

    return data.detail
