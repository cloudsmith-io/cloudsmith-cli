"""
Credential helper commands for Cloudsmith.

This module provides credential helper commands for various package managers
(Docker, pip, npm, etc.) that follow their respective credential helper protocols.
"""

import click

from ..main import main
from .cargo import cargo as cargo_cmd
from .docker import docker as docker_cmd
from .npm import npm as npm_cmd
from .nuget import nuget as nuget_cmd
from .terraform import terraform as terraform_cmd


@click.group()
def credential_helper():
    """
    Credential helpers for package managers.

    These commands provide credentials for package managers like Docker, pip,
    npm, Terraform, Cargo, and NuGet. They are typically called by
    wrapper binaries (e.g., docker-credential-cloudsmith) or used directly
    for debugging.

    Examples:
        # Test Docker credential helper
        $ echo "docker.cloudsmith.io" | cloudsmith credential-helper docker

        # Test Terraform credential helper
        $ cloudsmith credential-helper terraform terraform.cloudsmith.io

        # Test npm/pnpm token helper
        $ cloudsmith credential-helper npm
    """


credential_helper.add_command(cargo_cmd, name="cargo")
credential_helper.add_command(docker_cmd, name="docker")
credential_helper.add_command(npm_cmd, name="npm")
credential_helper.add_command(nuget_cmd, name="nuget")
credential_helper.add_command(terraform_cmd, name="terraform")

main.add_command(credential_helper, name="credential-helper")
