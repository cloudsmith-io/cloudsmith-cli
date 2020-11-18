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


def organization_entitlement_usage_metrics(owner=None, **kwargs):
    """List token usage metrics."""
    client = get_metrics_api()

    api_kwargs = {}
    api_kwargs.update(
        {param: value for param, value in kwargs.items() if value is not None}
    )

    headers = []
    res = None

    if owner:
        if hasattr(client, "metrics_entitlements_usage_list_with_http_info"):
            with catch_raise_api_exception():
                res, _, headers = client.metrics_entitlements_usage_list_with_http_info(
                    owner=owner, **api_kwargs
                )

    ratelimits.maybe_rate_limit(client, headers)
    return res if not res else res[0]


def entitlement_usage_metrics(owner=None, repo=None, **kwargs):
    """List token usage metrics."""
    client = get_metrics_api()

    api_kwargs = {}
    api_kwargs.update(
        {param: value for param, value in kwargs.items() if value is not None}
    )

    headers = []
    res = None

    if owner and repo:
        if hasattr(client, "metrics_entitlements_usage_list_with_http_info"):
            with catch_raise_api_exception():
                res, _, headers = client.metrics_entitlements_usage_list0_with_http_info(
                    owner=owner, repo=repo, **api_kwargs
                )

    ratelimits.maybe_rate_limit(client, headers)
    return res if not res else res[0]


def package_usage_metrics(owner=None, repo=None, **kwargs):
    """List package usage metrics."""
    client = get_metrics_api()

    api_kwargs = {}
    api_kwargs.update(
        {param: value for param, value in kwargs.items() if value is not None}
    )

    headers = []
    res = None

    if owner and repo:
        if hasattr(client, "metrics_packages_usage_list_with_http_info"):
            with catch_raise_api_exception():
                res, _, headers = client.metrics_packages_usage_list_with_http_info(
                    owner=owner, repo=repo, **api_kwargs
                )

    ratelimits.maybe_rate_limit(client, headers)
    return res if not res else res[0]
