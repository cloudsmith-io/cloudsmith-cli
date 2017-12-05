"""API - Files endpoints."""
from __future__ import absolute_import, print_function, unicode_literals

import cloudsmith_api

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
        distros = client.distros_list()

    if not package_format:
        return distros

    return [
        distro for distro in distros
        if distro.format == package_format
    ]
