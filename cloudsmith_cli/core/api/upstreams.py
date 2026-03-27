"""API - Packages endpoints."""

import cloudsmith_sdk

from ...core import utils
from .exceptions import catch_raise_api_exception
from .init import get_new_api_client


def get_upstreams_api() -> cloudsmith_sdk.ReposApi:
    """Get the upstreams API client."""
    return get_new_api_client().repos


def list_upstreams(owner, repo, upstream_format, page_size):
    """List upstreams by format in a repo."""
    client = get_upstreams_api()

    func = getattr(client, "upstream_%s_list" % upstream_format)
    with catch_raise_api_exception():
        return func(
            owner=owner, identifier=repo, **utils.get_page_kwargs(page_size=page_size)
        )


def create_upstream(owner, repo, upstream_format, upstream_config):
    """Create an upstream for a certain package format in a repo."""
    client = get_upstreams_api()

    func = getattr(client, "upstream_%s_create" % upstream_format)

    with catch_raise_api_exception():
        return func(owner=owner, identifier=repo, body=upstream_config)


def update_upstream(owner, repo, slug_perm, upstream_format, upstream_config):
    """Update an upstream belonging to a repo."""
    client = get_upstreams_api()
    func = getattr(client, "upstream_%s_partial_update" % upstream_format)

    with catch_raise_api_exception():
        return func(
            owner=owner, identifier=repo, slug_perm=slug_perm, body=upstream_config
        )


def delete_upstream(owner, repo, upstream_format, slug_perm):
    """Delete an upstream from a repo."""
    client = get_upstreams_api()

    func = getattr(client, "upstream_%s_delete" % upstream_format)

    with catch_raise_api_exception():
        func(owner=owner, identifier=repo, slug_perm=slug_perm)
