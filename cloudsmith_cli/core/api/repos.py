"""API - Packages endpoints."""
from __future__ import absolute_import, print_function, unicode_literals

import cloudsmith_api

from . import user
from .exceptions import catch_raise_api_exception
from .init import get_api_client


def get_repos_api():
    """Get the repos API client."""
    return get_api_client(cloudsmith_api.ReposApi)


def list_repos(owner=None):
    """List repositories in a namespace."""
    client = get_repos_api()

    # pylint: disable=fixme
    # TODO(ls): Add support on the server-side to list the repositories for the
    # current user instead of having to determine it. E.g. /user/self/repos or
    # something like that.
    if not owner:
        # FIXME: We really shouldn't return standard tuples
        _, owner, _, _ = user.get_user_brief()

    with catch_raise_api_exception():
        res = client.repos_list(owner=owner)

    return [x.to_dict() for x in res]
