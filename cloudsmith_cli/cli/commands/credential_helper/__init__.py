"""
Credential helper commands for Cloudsmith.

This module provides credential helper commands for package managers
that follow their respective credential helper protocols.
"""

import click

from ..main import main
from .docker import docker as docker_cmd
from .manage import install_cmd, list_cmd, uninstall_cmd


@click.group()
def credential_helper():
    """
    Credential helpers for package managers.

    These commands provide credentials for package managers like Docker.
    Use ``install`` to set up the on-PATH launcher and configure the package
    manager automatically, or run the runtime command directly for debugging.

    Examples:
        # Install Docker credential helper
        $ cloudsmith credential-helper install docker

        # Test Docker credential helper directly
        $ echo "docker.cloudsmith.io" | cloudsmith credential-helper docker
    """


credential_helper.add_command(docker_cmd, name="docker")
credential_helper.add_command(install_cmd, name="install")
credential_helper.add_command(uninstall_cmd, name="uninstall")
credential_helper.add_command(list_cmd, name="list")

main.add_command(credential_helper, name="credential-helper")
