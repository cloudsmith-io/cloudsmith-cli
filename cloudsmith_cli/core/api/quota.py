"""API - Quota endpoints."""

from .exceptions import catch_raise_api_exception
from .init import get_new_api_client


def get_quota_api():
    """Get the Quota API client."""
    return get_new_api_client().quota


def quota_limits(owner=None, oss=False, **kwargs):
    """Get Quota for namespace"""
    client = get_quota_api()

    api_kwargs = {}
    api_kwargs.update(
        {param: value for param, value in kwargs.items() if value is not None}
    )
    with catch_raise_api_exception():
        read_quota = getattr(client, "%sread" % ("oss_" if oss else ""))
        return read_quota(owner=owner, **api_kwargs)


def quota_history(owner=None, oss=False, **kwargs):
    """Get Quota history for namespace"""
    client = get_quota_api()

    api_kwargs = {}
    api_kwargs.update(
        {param: value for param, value in kwargs.items() if value is not None}
    )

    with catch_raise_api_exception():
        read_history = getattr(client, "%shistory_read" % ("oss_" if oss else ""))
        return read_history(owner=owner, **api_kwargs)
