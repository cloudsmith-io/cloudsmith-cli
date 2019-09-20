# -*- coding: utf-8 -*-
"""Cloudsmith CLI."""
import click
import urllib3

click.disable_unicode_literals_warning = True
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
