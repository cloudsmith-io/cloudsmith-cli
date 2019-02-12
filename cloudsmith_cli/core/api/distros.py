# -*- coding: utf-8 -*-
"""API - Files endpoints."""
from __future__ import absolute_import, print_function, unicode_literals

import cloudsmith_api

from .. import ratelimits
from .exceptions import catch_raise_api_exception
from .init import get_api_client


def get_distros_api():
    """Get the distros API client."""
    return get_api_client(cloudsmith_api.DistrosApi)


def list_distros(package_format=None):
    """List available distributions."""
    client = get_distros_api()

    # pylint: disable=fixme
    # TODO(ls): Add package format param on the server-side to filter distros
    # instead of doing it here.
    with catch_raise_api_exception():
        distros, _, headers = client.distros_list_with_http_info()

    ratelimits.maybe_rate_limit(client, headers)

    return [
        distro.to_dict()
        for distro in distros
        if not package_format or distro.format == package_format
    ]
