# Copyright 2026 Cloudsmith Ltd
"""``cloudsmith credential-helper shell-init`` — print shell init for shims.

Add ``eval "$(cloudsmith credential-helper shell-init)"`` to your shell rc file
to put the Cloudsmith shims directory ahead of the real package-manager
binaries on ``$PATH``.
"""

import click

from ....credential_helpers.shellplugin.shellinit import detect_shell, generate_init


@click.command(name="shell-init")
@click.option(
    "--shell",
    "shell_name",
    type=click.Choice(["bash", "zsh", "fish"]),
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
    shell = shell_name or detect_shell()
    click.echo(generate_init(shell), nl=False)
