# -*- coding: utf-8 -*-
"""Cloudsmith CLI - Main script."""
from __future__ import absolute_import, print_function, unicode_literals

from .cli.commands.main import main

if __name__ == "__main__":
    # Disable false positive for parameters handled by click.
    # pylint: disable=no-value-for-parameter
    main()
