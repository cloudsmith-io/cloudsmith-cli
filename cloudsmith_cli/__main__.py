"""Cloudsmith CLI - Main script."""

from .cli.commands.main import main

if __name__ == "__main__":
    # Disable false positive for parameters handled by click.
    # pylint: disable=no-value-for-parameter
    main()
