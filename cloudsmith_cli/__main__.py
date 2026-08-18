"""Cloudsmith CLI - Main script."""

import sys

from .cli.commands.main import main

if __name__ == "__main__":
    # sys.exit() is required: AliasGroup.main runs click with
    # standalone_mode=False, so click returns the exit code (e.g. from
    # ctx.exit()) instead of raising SystemExit. The console script and the
    # PyInstaller entry point wrap main() in sys.exit() too; a bare main()
    # call would discard the code and always exit 0.
    # Disable false positive for parameters handled by click.
    # pylint: disable=no-value-for-parameter
    sys.exit(main())
