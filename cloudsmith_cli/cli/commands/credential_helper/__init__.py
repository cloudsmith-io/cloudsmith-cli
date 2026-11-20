# Copyright 2026 Cloudsmith Ltd
"""
Credential helper commands for Cloudsmith.

This module provides credential helper commands for package managers
that follow their respective credential helper protocols.
"""

import click

from ..main import main
from .cargo import cargo as cargo_cmd
from .docker import docker as docker_cmd
from .generic import generic as generic_cmd
from .manage import install_cmd, list_cmd, uninstall_cmd
from .pnpm import pnpm as pnpm_cmd
from .terraform import terraform as terraform_cmd


@click.group()
def credential_helper():
    """
    Credential helpers for package managers.

    These commands provide credentials for package managers. Use ``install``
    to set up a helper and configure the package manager automatically, and
    ``list`` to see every helper and whether it is installed.

    \b
    Helpers: cargo, docker, gradle, maven, pnpm, sbt, terraform.

    Docker, pnpm, cargo and Terraform call the runtime command of the same
    name, which you can also run directly for debugging. Maven, Gradle and
    sbt load a Cloudsmith extension or plugin that gets credentials from
    ``generic``, so they have no runtime command of their own.

    Examples:

    \b
        # Install Docker credential helper
        $ cloudsmith credential-helper install docker
    \b
        # Install pnpm credential helper
        $ cloudsmith credential-helper install pnpm
    \b
        # Install cargo credential helper
        $ cloudsmith credential-helper install cargo
    \b
        # Install the Maven extension (also: gradle, sbt)
        $ cloudsmith credential-helper install maven
    \b
        # List the helpers and their installation status
        $ cloudsmith credential-helper list
    \b
        # Test Docker credential helper directly
        $ echo "docker.cloudsmith.io" | cloudsmith credential-helper docker
    \b
        # Test pnpm credential helper directly
        $ cloudsmith credential-helper pnpm npm.cloudsmith.io
    """


credential_helper.add_command(pnpm_cmd, name="pnpm")
credential_helper.add_command(docker_cmd, name="docker")
credential_helper.add_command(generic_cmd, name="generic")
credential_helper.add_command(install_cmd, name="install")
credential_helper.add_command(uninstall_cmd, name="uninstall")
credential_helper.add_command(list_cmd, name="list")
credential_helper.add_command(cargo_cmd, name="cargo")
credential_helper.add_command(terraform_cmd, name="terraform")

main.add_command(credential_helper, name="credential-helper")
