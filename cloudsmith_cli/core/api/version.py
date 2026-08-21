"""API version utilities."""

import importlib.metadata


def get_version():
    """Get the raw/unparsed version of the API as a string."""
    return importlib.metadata.version("cloudsmith_api")


def get_version_info():
    """Get the API version as VersionInfo object."""
    # semver costs ~6ms to import and only version comparisons need it.
    import semver

    return semver.parse_version_info(get_version())
