"""API - Status endpoints."""

import cloudsmith_sdk

from .exceptions import catch_raise_api_exception
from .init import get_new_api_client


def get_status_api() -> cloudsmith_sdk.StatusApi:
    """Get the status API client."""
    return get_new_api_client().status


def get_status(with_version=False):
    """Retrieve status (and optionally) version from the API."""
    client = get_status_api()

    with catch_raise_api_exception():
        data = client.check_basic()

    if with_version:
        return data.detail, data.version

    return data.detail
