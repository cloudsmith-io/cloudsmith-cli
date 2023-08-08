"""CLI/Commands - Custom types."""

import os

import click


class ExpandPath(click.Path):
    """Extends Path to provide expanded user $HOME paths."""

    def convert(self, value, *args, **kwargs):  # pylint: disable=arguments-differ
        """Take a path with $HOME variables and resolve it to full path."""
        value = os.path.expanduser(value)
        return super().convert(value, *args, **kwargs)
