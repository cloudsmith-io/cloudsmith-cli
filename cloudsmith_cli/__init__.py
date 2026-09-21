"""Cloudsmith CLI."""

import sys
import warnings

import click

from .cli.utils import configure_rich

click.disable_unicode_literals_warning = True
warnings.filterwarnings("ignore", category=ResourceWarning)

# ensure rich tables do not wrap in non-tty envs
configure_rich()
