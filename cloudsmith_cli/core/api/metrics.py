# -*- coding: utf-8 -*-
"""API - Metrics endpoints."""
from __future__ import absolute_import, print_function, unicode_literals

import cloudsmith_api

from .. import ratelimits
from .exceptions import catch_raise_api_exception
from .init import get_api_client


def get_metrics_api():
    """Get the repos API client."""
    return get_api_client(cloudsmith_api.MetricsApi)


def get_namespace_entitlements_metrics(owner=None, **kwargs):
    """Get repository entitlements metrics."""
    client = get_metrics_api()

    api_kwargs = {}
    api_kwargs.update(
        {param: value for param, value in kwargs.items() if value is not None}
    )

    headers = []
    res = None

    if owner:
        with catch_raise_api_exception():
            res, _, headers = client.metrics_entitlements_list_with_http_info(
                owner=owner, **api_kwargs
            )

    ratelimits.maybe_rate_limit(client, headers)
    return res.tokens if res else {}


def get_repository_entitlements_metrics(owner=None, repo=None, **kwargs):
    """Get repository entitlements metrics."""
    client = get_metrics_api()

    api_kwargs = {}
    api_kwargs.update(
        {param: value for param, value in kwargs.items() if value is not None}
    )

    headers = []
    res = None

    if owner and repo:
        with catch_raise_api_exception():
            res, _, headers = client.metrics_entitlements_list0_with_http_info(
                owner=owner, repo=repo, **api_kwargs
            )

    ratelimits.maybe_rate_limit(client, headers)
    return res.tokens if res else {}


def get_repository_packages_metrics(owner=None, repo=None, **kwargs):
    """Get repository packages metrics."""
    client = get_metrics_api()

    api_kwargs = {}
    api_kwargs.update(
        {param: value for param, value in kwargs.items() if value is not None}
    )

    headers = []
    res = None

    if owner and repo:
        with catch_raise_api_exception():
            res, _, headers = client.metrics_packages_list_with_http_info(
                owner=owner, repo=repo, **api_kwargs
            )

    ratelimits.maybe_rate_limit(client, headers)
    return res.packages if res else {}
