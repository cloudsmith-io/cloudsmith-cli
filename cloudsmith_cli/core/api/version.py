"""API version utilities."""

import importlib.metadata

import semver


def get_version():
    """Get the raw/unparsed version of the API as a string."""
    return importlib.metadata.version("cloudsmith_api")


def get_version_info():
    """Get the API version as VersionInfo object."""
    return semver.parse_version_info(get_version())
