# -*- coding: utf-8 -*-
"""Core utilities."""
from __future__ import absolute_import, print_function, unicode_literals

import hashlib
import os

import click


def get_help_website():
    """Get the URL for the help website."""
    return "https://help.cloudsmith.io/docs/cli/"


def get_github_website():
    """Get the URL for the GitHub project."""
    return "https://github.com/cloudsmith-io/cloudsmith-cli"


def get_root_path():
    """Get the root directory for the application."""
    return os.path.realpath(os.path.join(os.path.dirname(__file__), os.pardir))


def get_data_path():
    """Get the data directory for the application."""
    return os.path.join(get_root_path(), "data")


def read_file(*path):
    """Read the specific file into a string in its entirety."""
    real_path = os.path.realpath(os.path.join(*path))
    with click.open_file(real_path, "r") as fp:
        return fp.read()


def calculate_file_md5(filepath, blocksize=2 ** 20):
    """Calculate an MD5 hash for a file."""
    checksum = hashlib.md5()

    with click.open_file(filepath, "rb") as f:

        def update_chunk():
            """Add chunk to checksum."""
            buf = f.read(blocksize)
            if buf:
                checksum.update(buf)
            return bool(buf)

        while update_chunk():
            pass

    return checksum.hexdigest()


def get_file_size(filepath):
    """Get the size of a file in bytes."""
    statinfo = os.stat(filepath)
    return statinfo.st_size


def get_page_kwargs(**kwargs):
    """Construct page and page size kwargs (if present)."""
    page_kwargs = {}

    page = kwargs.get("page")
    if page is not None and page > 0:
        page_kwargs["page"] = page

    page_size = kwargs.get("page_size")
    if page_size is not None and page_size > 0:
        page_kwargs["page_size"] = page_size

    return page_kwargs


def get_query_kwargs(**kwargs):
    """Construct page and page size kwargs (if present)."""
    query_kwargs = {}

    query = kwargs.pop("query")
    if query:
        query_kwargs["query"] = query

    return query_kwargs
