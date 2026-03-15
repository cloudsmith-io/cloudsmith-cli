"""
Credential helper commands for Cloudsmith.

This module provides credential helper commands for package managers
that follow their respective credential helper protocols.
"""

import click

from ..main import main
from .docker import docker as docker_cmd


@click.group()
def credential_helper():
    """
    Credential helpers for package managers.

    These commands provide credentials for package managers like Docker.
    They are typically called by wrapper binaries
    (e.g., docker-credential-cloudsmith) or used directly for debugging.

    Examples:
        # Test Docker credential helper
        $ echo "docker.cloudsmith.io" | cloudsmith credential-helper docker
    """


credential_helper.add_command(docker_cmd, name="docker")

main.add_command(credential_helper, name="credential-helper")
