"""Core utilities."""

import hashlib
import os
from enum import Flag, auto

import click


def get_help_website():
    """Get the URL for the help website."""
    return "https://docs.cloudsmith.com/developer-tools/cli"


class ColorMode(Flag):
    AUTO = 0
    ALWAYS = auto()
    NEVER = auto()


class TTYMode(Flag):
    ENABLED = auto()
    DISABLED = auto()


def color_enabled(env: dict[str, str], colorMode: ColorMode, ttyMode: TTYMode) -> bool:
    """Checks based on environment and"""
    match colorMode:
        case ColorMode.ALWAYS:
            return True
        case ColorMode.NEVER:
            return False
        case ColorMode.AUTO:
            pass

    if env.get("NO_COLOR"):
        return False
    if env.get("CLOUDSMITH_FORCE_COLOR") == "true":
        return True
    if env.get("TERM") == "dumb":
        return False

    match ttyMode:
        case TTYMode.ENABLED:
            return True
        case TTYMode.DISABLED:
            return False
    return True


def is_interactive(env: dict[str, str], ttyMode: TTYMode) -> bool:
    if env.get("CI") == "true":
        return False

    match ttyMode:
        case TTYMode.ENABLED:
            return True
        case TTYMode.DISABLED:
            return False
    return True


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


def calculate_file_md5(filepath, blocksize=2**20):
    """Calculate an MD5 hash for a file."""
    checksum = hashlib.md5(usedforsecurity=False)

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


def get_sort_kwargs(**kwargs):
    """Construct sort kwargs (if present)."""
    sort_kwargs = {}

    sort = kwargs.get("sort")
    if sort:
        sort_kwargs["sort"] = sort

    return sort_kwargs
