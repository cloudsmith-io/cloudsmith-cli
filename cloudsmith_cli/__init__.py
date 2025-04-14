"""Cloudsmith CLI."""

import warnings

import click
import urllib3

click.disable_unicode_literals_warning = True
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=ResourceWarning)
