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


def usage_metrics(owner=None, repo=None, **kwargs):
    """List usage metrics for a namespace."""
    client = get_metrics_api()

    api_kwargs = {}
    api_kwargs.update(**kwargs)

    if owner and repo:
        if hasattr(client, "metrics_entitlements_usage_list_with_http_info"):
            with catch_raise_api_exception():
                res, _, headers = client.metrics_entitlements_usage_list_with_http_info(
                    owner=owner, repo=repo, **api_kwargs
                )

    ratelimits.maybe_rate_limit(client, headers)
    return res if not res else res[0]
