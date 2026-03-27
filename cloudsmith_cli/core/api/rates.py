"""API - Status endpoints."""

import cloudsmith_sdk

from ..ratelimits import RateLimitsInfo
from .exceptions import catch_raise_api_exception
from .init import get_new_api_client


def get_rates_api() -> cloudsmith_sdk.RatesApi:
    """Get the status API client."""
    return get_new_api_client().rates


def get_rate_limits():
    """Retrieve status (and optionally) version from the API."""
    client = get_rates_api()

    with catch_raise_api_exception():
        data = client.limits_list()

    return {
        k: RateLimitsInfo.from_dict(v)
        for k, v in data.to_dict().get("resources", {}).items()
    }
