"""API - Metrics endpoints."""

import cloudsmith_sdk

from .exceptions import catch_raise_api_exception
from .init import get_new_api_client


def get_metrics_api() -> cloudsmith_sdk.MetricsApi:
    """Get the metrics API client."""
    return get_new_api_client().metrics


def get_namespace_entitlements_metrics(owner=None, **kwargs):
    """Get repository entitlements metrics."""
    client = get_metrics_api()

    api_kwargs = {}
    api_kwargs.update(
        {param: value for param, value in kwargs.items() if value is not None}
    )

    with catch_raise_api_exception():
        return client.entitlements_account_list(owner=owner, **api_kwargs).tokens


def get_repository_entitlements_metrics(owner=None, repo=None, **kwargs):
    """Get repository entitlements metrics."""
    client = get_metrics_api()

    api_kwargs = {}
    api_kwargs.update(
        {param: value for param, value in kwargs.items() if value is not None}
    )

    if owner and repo:
        with catch_raise_api_exception():
            return client.entitlements_repo_list(
                owner=owner, repo=repo, **api_kwargs
            ).tokens


def get_repository_packages_metrics(owner=None, repo=None, **kwargs):
    """Get repository packages metrics."""
    client = get_metrics_api()

    api_kwargs = {}
    api_kwargs.update(
        {param: value for param, value in kwargs.items() if value is not None}
    )

    if owner and repo:
        with catch_raise_api_exception():
            return client.packages_list(owner=owner, repo=repo, **api_kwargs).packages
