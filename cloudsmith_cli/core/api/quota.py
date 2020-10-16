# -*- coding: utf-8 -*-
"""API - Quota endpoints."""
from __future__ import absolute_import, print_function, unicode_literals

import cloudsmith_api

from .. import ratelimits
from .exceptions import catch_raise_api_exception
from .init import get_api_client


def get_quota_api():
    """Get the Quota API client."""
    return get_api_client(cloudsmith_api.QuotaApi)


def quota_limits(owner=None, oss=False, **kwargs):
    """Get Quota for namespace"""
    client = get_quota_api()

    api_kwargs = {}
    api_kwargs.update(
        {param: value for param, value in kwargs.items() if value is not None}
    )

    if oss:
        if hasattr(client, "quota_oss_read_with_http_info"):
            with catch_raise_api_exception():
                res, _, headers = client.quota_oss_read_with_http_info(
                    owner=owner, **api_kwargs
                )
    elif not oss:
        if hasattr(client, "quota_read_with_http_info"):
            with catch_raise_api_exception():
                res, _, headers = client.quota_read_with_http_info(
                    owner=owner, **api_kwargs
                )

    ratelimits.maybe_rate_limit(client, headers)
    return res if not res else res


def quota_history(owner=None, oss=False, **kwargs):
    """Get Quota history for namespace"""
    client = get_quota_api()

    api_kwargs = {}
    api_kwargs.update(
        {param: value for param, value in kwargs.items() if value is not None}
    )

    if oss:
        if hasattr(client, "quota_oss_history_read_with_http_info"):
            with catch_raise_api_exception():
                res, _, headers = client.quota_oss_history_read_with_http_info(
                    owner=owner, **api_kwargs
                )
    elif not oss:
        if hasattr(client, "quota_history_read_with_http_info"):
            with catch_raise_api_exception():
                res, _, headers = client.quota_history_read_with_http_info(
                    owner=owner, **api_kwargs
                )

    ratelimits.maybe_rate_limit(client, headers)
    return res if not res else res
