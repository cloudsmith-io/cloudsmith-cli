"""CLI/Commands - Custom types."""
from __future__ import absolute_import, print_function, unicode_literals

import os

import click


class ExpandPath(click.Path):
    """Extends Path to provide expanded user $HOME paths."""

    def convert(self, value, *args, **kwargs):
        """Take a path with $HOME variables and resolve it to full path."""
        value = os.path.expanduser(value)
        return super(ExpandPath, self).convert(value, *args, **kwargs)
