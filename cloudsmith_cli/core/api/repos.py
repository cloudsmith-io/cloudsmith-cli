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

    if owner:
        repo = kwargs.get("repo", None)
        if repo is not None:
            if hasattr(client, "repos_read_with_http_info"):
                with catch_raise_api_exception():
                    res, _, headers = client.repos_read_with_http_info(owner, repo)
                    res = [res]
        else:
            api_kwargs["owner"] = owner

            if hasattr(client, "repos_list_with_http_info"):
                with catch_raise_api_exception():
                    res, _, headers = client.repos_list_with_http_info(**api_kwargs)
    else:
        if hasattr(client, "repos_all_list_with_http_info"):
            with catch_raise_api_exception():
                res, _, headers = client.repos_all_list_with_http_info(**api_kwargs)

    ratelimits.maybe_rate_limit(client, headers)
    page_info = PageInfo.from_headers(headers)
    return [x.to_dict() for x in res], page_info


def create_repo(owner, repo_config):
    """Create a repository in a namespace."""
    client = get_repos_api()

    with catch_raise_api_exception():
        data, _, headers = client.repos_create_with_http_info(
            owner=owner, data=repo_config
        )

    ratelimits.maybe_rate_limit(client, headers)
    return data.to_dict()


def update_repo(owner, repo, repo_config):
    """Update a repo in a namespace."""
    client = get_repos_api()

    with catch_raise_api_exception():
        data, _, headers = client.repos_partial_update_with_http_info(
            owner, repo, data=repo_config
        )

    ratelimits.maybe_rate_limit(client, headers)
    return data.to_dict()


def delete_repo(owner, repo):
    """Delete a repo from a namespace."""
    client = get_repos_api()

    with catch_raise_api_exception():
        _, _, headers = client.repos_delete_with_http_info(owner, repo)

    ratelimits.maybe_rate_limit(client, headers)
