# -*- coding: utf-8 -*-
"""Core version utilities."""
from __future__ import absolute_import, print_function, unicode_literals

import semver

from . import utils


def get_version():
    """Get the raw/unparsed version of the application as a string."""
    return utils.read_file(utils.get_data_path(), "VERSION").strip()


def get_version_info():
    """Get the application version as a VersionInfo object."""
    return parse_version(get_version())


def parse_version(version):
    """Get a version string as a VersionInfo object."""
    return semver.parse_version_info(version)
