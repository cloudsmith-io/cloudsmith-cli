"""API - Overages endpoints."""

import cloudsmith_api

from .. import ratelimits
from .exceptions import catch_raise_api_exception
from .init import get_api_client


def get_overages_api():
    """Get the Overages API client."""
    return get_api_client(cloudsmith_api.UsageLimits)


def overages(owner=None, **kwargs):
    """Get Overages for namespace."""
    client = get_overages_api()

    api_kwargs = {}
    api_kwargs.update(
        {param: value for param, value in kwargs.items() if value is not None}
    )

    with catch_raise_api_exception():
        res, _, headers = client.storage(
            owner=owner, **api_kwargs
        )

    ratelimits.maybe_rate_limit(client, headers)
    return res if not res else res