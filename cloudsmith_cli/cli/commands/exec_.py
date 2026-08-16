# Copyright 2026 Cloudsmith Ltd
"""CLI/Commands - Run a command with Cloudsmith credentials provisioned."""

import sys

import click

from ...credential_helpers.maven import runner
from ..decorators import common_api_auth_options, resolve_credentials
from .main import main


@main.command(name="exec", context_settings={"ignore_unknown_options": True})
@click.argument("command", nargs=-1, type=click.UNPROCESSED, required=True)
@common_api_auth_options
@resolve_credentials
@click.pass_context
def exec_(ctx, opts, command):
    """Run a package-manager command authenticated against Cloudsmith.

    Wraps the command so it resolves dependencies from your Cloudsmith
    repository, with credentials injected for that run and removed afterwards.
    This is the machinery the ``mvn`` shim uses, callable directly in CI
    without touching ``PATH``.

    Maven runs use a generated ``settings.xml``; your ``~/.m2/settings.xml``
    is not consulted. The repository comes from ``credential-helper install
    maven``. The package manager is detected from the command, so just put it
    after ``--``:

    \b
        $ cloudsmith exec -- mvn clean install
    """
    sys.exit(runner.run(list(command), credential=opts.credential))
