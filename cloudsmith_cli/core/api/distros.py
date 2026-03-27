"""API - Files endpoints."""

import cloudsmith_sdk

from .exceptions import catch_raise_api_exception
from .init import get_new_api_client


def get_distros_api() -> cloudsmith_sdk.DistrosApi:
    """Get the distros API client."""
    return get_new_api_client().distros


def list_distros(package_format=None):
    """List available distributions."""
    client = get_distros_api()

    # pylint: disable=fixme
    # TODO(ls): Add package format param on the server-side to filter distros
    # instead of doing it here.
    with catch_raise_api_exception():
        distros = client.list()

    return [
        distro.to_dict()
        for distro in distros
        if not package_format or distro.format == package_format
    ]
