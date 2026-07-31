# Copyright 2026 Cloudsmith Ltd
"""
Credential helper commands for Cloudsmith.

This module provides credential helper commands for package managers
that follow their respective credential helper protocols.
"""

import click

from ..main import main
from .docker import docker as docker_cmd
from .domains import domains_cmd
from .generic import generic as generic_cmd
from .manage import install_cmd, list_cmd, uninstall_cmd
from .shell import shell_init


@click.group()
def credential_helper():
    """
    Credential helpers for package managers.

    Use ``install`` to set up a helper and configure the package manager
    automatically. Docker uses a native credential-helper launcher; Maven has
    no such protocol, so it uses an ``mvn`` shim plus ``cloudsmith exec`` —
    activate the shims directory with ``credential-helper shell-init``.

    ``generic`` and ``domains`` emit machine-readable JSON for tools that
    shell out to the CLI instead of importing it.

    Examples:

    \b
        # Install the Docker credential helper
        $ cloudsmith credential-helper install docker

    \b
        # Install the Maven helper for one repository
        $ cloudsmith credential-helper install maven --org my-org --repo my-repo

    \b
        # Test the Docker credential helper directly
        $ echo "docker.cloudsmith.io" | cloudsmith credential-helper docker

    \b
        # Emit a credential as JSON
        $ cloudsmith credential-helper generic
    """


credential_helper.add_command(docker_cmd, name="docker")
credential_helper.add_command(domains_cmd, name="domains")
credential_helper.add_command(generic_cmd, name="generic")
credential_helper.add_command(shell_init, name="shell-init")
credential_helper.add_command(install_cmd, name="install")
credential_helper.add_command(uninstall_cmd, name="uninstall")
credential_helper.add_command(list_cmd, name="list")

main.add_command(credential_helper, name="credential-helper")
