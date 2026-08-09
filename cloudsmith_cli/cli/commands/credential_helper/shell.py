# Copyright 2026 Cloudsmith Ltd
"""``cloudsmith credential-helper shell-init`` — print shell init for shims.

Add ``eval "$(cloudsmith credential-helper shell-init)"`` to your shell rc file
to put the Cloudsmith shims directory ahead of the real package-manager
binaries on ``$PATH``.
"""

import os

import click

from ....credential_helpers.maven.config import shims_dir

_COMMENT = "# Put Cloudsmith package-manager shims ahead of the real binaries"

_POSIX_STATEMENT = 'export PATH="{path}:$PATH"'

_STATEMENTS = {
    "bash": _POSIX_STATEMENT,
    "zsh": _POSIX_STATEMENT,
    "fish": 'fish_add_path "{path}"',
}


def detect_shell():
    """Best-effort shell detection from ``$SHELL``, defaulting to bash."""
    name = os.path.basename(os.environ.get("SHELL", ""))
    return name if name in _STATEMENTS else "bash"


@click.command(name="shell-init")
@click.option(
    "--shell",
    "shell_name",
    type=click.Choice(sorted(_STATEMENTS)),
    default=None,
    help="Target shell. Auto-detected from $SHELL when omitted.",
)
def shell_init(shell_name):
    """Print shell init that puts the Cloudsmith shims dir first on PATH.

    Examples:

    \b
        # bash / zsh
        $ eval "$(cloudsmith credential-helper shell-init)"

    \b
        # fish
        $ cloudsmith credential-helper shell-init --shell fish | source
    """
    statement = _STATEMENTS[shell_name or detect_shell()]
    click.echo(_COMMENT)
    click.echo(statement.format(path=shims_dir()))
