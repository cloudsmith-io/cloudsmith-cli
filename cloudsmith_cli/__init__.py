"""Cloudsmith CLI."""

import warnings

import click

click.disable_unicode_literals_warning = True
warnings.filterwarnings("ignore", category=ResourceWarning)
