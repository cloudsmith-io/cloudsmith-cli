# -*- coding: utf-8 -*-
"""API - Packages endpoints."""
from __future__ import absolute_import, print_function, unicode_literals

import cloudsmith_api

from .. import ratelimits, utils
from ..pagination import PageInfo
from .exceptions import catch_raise_api_exception
from .init import get_api_client


def get_repos_api():
    """Get the repos API client."""
    return get_api_client(cloudsmith_api.ReposApi)


def list_repos(owner=None, **kwargs):
    """List repositories in a namespace."""
    client = get_repos_api()

    api_kwargs = {}
    api_kwargs.update(utils.get_page_kwargs(**kwargs))

    # pylint: disable=fixme
    # FIXME: Compatibility code until we work out how to conflate
    # the overlapping repos_list methods into one.
    repos_list = client.repos_list_with_http_info

    if owner is not None:
        api_kwargs["owner"] = owner
        if hasattr(client, "repos_list0_with_http_info"):
            # pylint: disable=no-member
            repos_list = client.repos_list0_with_http_info
    else:
        if hasattr(client, "repos_all_list_with_http_info"):
            # pylint: disable=no-member
            repos_list = client.repos_all_list_with_http_info

    with catch_raise_api_exception():
        res, _, headers = repos_list(**api_kwargs)

    ratelimits.maybe_rate_limit(client, headers)
    page_info = PageInfo.from_headers(headers)
    return [x.to_dict() for x in res], page_info
