# -*- coding: utf-8 -*-
"""API - Status endpoints."""
from __future__ import absolute_import, print_function, unicode_literals

import cloudsmith_api
import six

from .. import ratelimits
from ..ratelimits import RateLimitsInfo
from .exceptions import catch_raise_api_exception
from .init import get_api_client


def get_rates_api():
    """Get the status API client."""
    return get_api_client(cloudsmith_api.RatesApi)


def get_rate_limits():
    """Retrieve status (and optionally) version from the API."""
    client = get_rates_api()

    with catch_raise_api_exception():
        data, _, headers = client.rates_limits_list_with_http_info()

    ratelimits.maybe_rate_limit(client, headers)

    return {
        k: RateLimitsInfo.from_dict(v)
        for k, v in six.iteritems(data.to_dict().get("resources", {}))
    }
