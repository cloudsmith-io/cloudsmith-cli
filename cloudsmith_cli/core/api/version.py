"""API version utilities."""
from __future__ import absolute_import, print_function, unicode_literals

import pkg_resources
import semver


def get_version():
    """Get the raw/unparsed version of the API as a string."""
    package = pkg_resources.require('cloudsmith_api')[0]
    return package.version


def get_version_info():
    """Get the API version as VersionInfo object."""
    return semver.parse_version_info(get_version())
