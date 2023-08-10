"""API - Packages endpoints."""

import cloudsmith_api

from ...core import utils
from .. import ratelimits
from ..pagination import PageInfo
from .exceptions import catch_raise_api_exception
from .init import get_api_client


def get_upstreams_api():
    """Get the upstreams API client."""
    return get_api_client(cloudsmith_api.ReposApi)


def list_upstreams(owner, repo, upstream_format, page, page_size):
    """List upstreams by format in a repo."""
    client = get_upstreams_api()

    func = getattr(client, "repos_upstream_%s_list_with_http_info" % upstream_format)

    with catch_raise_api_exception():
        upstreams, _, headers = func(
            owner, repo, **utils.get_page_kwargs(page=page, page_size=page_size)
        )

    ratelimits.maybe_rate_limit(client, headers)
    page_info = PageInfo.from_headers(headers)
    return [upstream.to_dict() for upstream in upstreams], page_info


def create_upstream(owner, repo, upstream_format, upstream_config):
    """Create an upstream for a certain package format in a repo."""
    client = get_upstreams_api()

    func = getattr(client, "repos_upstream_%s_create_with_http_info" % upstream_format)

    with catch_raise_api_exception():
        upstream, _, headers = func(owner=owner, identifier=repo, data=upstream_config)

    ratelimits.maybe_rate_limit(client, headers)
    return upstream.to_dict()


def update_upstream(owner, repo, slug_perm, upstream_format, upstream_config):
    """Update an upstream belonging to a repo."""
    client = get_upstreams_api()

    func = getattr(
        client, "repos_upstream_%s_partial_update_with_http_info" % upstream_format
    )

    with catch_raise_api_exception():
        upstream, _, headers = func(
            owner=owner, identifier=repo, slug_perm=slug_perm, data=upstream_config
        )

    ratelimits.maybe_rate_limit(client, headers)
    return upstream.to_dict()


def delete_upstream(owner, repo, upstream_format, slug_perm):
    """Delete an upstream from a repo."""
    client = get_upstreams_api()

    func = getattr(client, "repos_upstream_%s_delete_with_http_info" % upstream_format)

    with catch_raise_api_exception():
        _, _, headers = func(owner, repo, slug_perm)

    ratelimits.maybe_rate_limit(client, headers)
