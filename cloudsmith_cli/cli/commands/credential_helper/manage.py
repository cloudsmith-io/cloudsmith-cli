# Copyright 2026 Cloudsmith Ltd
"""Install/uninstall/list commands for credential helpers.

Provides ``credential-helper install``, ``credential-helper uninstall``, and
``credential-helper list`` to manage the on-PATH launcher binary and the
``config.json`` entries for each supported credential helper.
"""

from __future__ import annotations

import os
import sys

import click

from ....credential_helpers.docker.installer import DockerInstaller
from ...decorators import common_api_auth_options, resolve_credentials

# ---------------------------------------------------------------------------
# Helper registry — extend here when new helpers are added
# ---------------------------------------------------------------------------

_INSTALLERS: dict[str, type] = {
    "docker": DockerInstaller,
}


def _get_installer(name: str):
    """Return an instantiated installer for *name*, or exit with a clear error.

    Parameters
    ----------
    name:
        The helper name as supplied by the user (e.g. ``"docker"``).

    Returns
    -------
    DockerInstaller
        An instance of the appropriate installer class.

    Raises
    ------
    SystemExit
        If *name* is not in :data:`_INSTALLERS`.
    """
    cls = _INSTALLERS.get(name)
    if cls is None:
        available = ", ".join(sorted(_INSTALLERS))
        click.echo(
            f"Error: unknown helper {name!r}. Available helpers: {available}",
            err=True,
        )
        sys.exit(1)
    return cls()


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------


@click.command("install")
@click.argument("helper")
@click.option(
    "--bin-dir", default=None, help="Directory to install the launcher binary."
)
@click.option(
    "--domain",
    "domains",
    multiple=True,
    help="Additional registry hostname to configure (repeatable).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be done without making any changes.",
)
@click.option(
    "--no-discover",
    is_flag=True,
    default=False,
    help="Disable automatic discovery of custom Docker domains.",
)
@click.option(
    "--refresh",
    is_flag=True,
    default=False,
    help="Bypass the custom-domain cache and fetch fresh data from the API.",
)
@click.option(
    "--org",
    default=None,
    help="Cloudsmith organisation slug for custom-domain discovery.",
)
@common_api_auth_options
@resolve_credentials
def install_cmd(
    opts,
    helper: str,
    bin_dir: str | None,
    domains: tuple[str, ...],
    dry_run: bool,
    no_discover: bool,
    refresh: bool,
    org: str | None,
) -> None:
    """Install a credential helper launcher and configure the package manager.

    HELPER is the name of the credential helper to install (e.g. ``docker``).

    Examples:

    \b
        # Install Docker credential helper
        $ cloudsmith credential-helper install docker

    \b
        # Install with a custom domain
        $ cloudsmith credential-helper install docker --domain my.registry.example.com

    \b
        # Preview without making changes
        $ cloudsmith credential-helper install docker --dry-run

    \b
        # Disable automatic custom-domain discovery
        $ cloudsmith credential-helper install docker --no-discover
    """
    installer = _get_installer(helper)
    org = org or os.environ.get("CLOUDSMITH_ORG", "").strip() or None
    api_key = opts.credential.api_key if opts.credential else None
    auth_type = (
        getattr(opts.credential, "auth_type", "api_key")
        if opts.credential
        else "api_key"
    )
    try:
        actions = installer.install(
            bin_dir=bin_dir,
            domains=domains,
            dry_run=dry_run,
            discover=not no_discover,
            refresh=refresh,
            org=org,
            api_key=api_key,
            auth_type=auth_type,
            api_host=opts.api_host,
        )
    except OSError as exc:
        raise click.ClickException(
            f"Failed to install {helper!r} credential helper: {exc}"
        )

    if dry_run:
        click.echo("Dry run — no changes will be made:")
    for action in actions:
        if action.startswith("WARNING"):
            click.secho(f"  {action}" if dry_run else action, err=True, fg="yellow")
        else:
            click.echo(f"  {action}" if dry_run else action)


# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------


@click.command("uninstall")
@click.argument("helper")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be done without making any changes.",
)
def uninstall_cmd(helper: str, dry_run: bool) -> None:
    """Uninstall a credential helper launcher and remove its config entries.

    HELPER is the name of the credential helper to uninstall (e.g. ``docker``).

    Examples:

    \b
        # Uninstall Docker credential helper
        $ cloudsmith credential-helper uninstall docker

    \b
        # Preview without making changes
        $ cloudsmith credential-helper uninstall docker --dry-run
    """
    installer = _get_installer(helper)
    try:
        actions = installer.uninstall(dry_run=dry_run)
    except OSError as exc:
        raise click.ClickException(
            f"Failed to uninstall {helper!r} credential helper: {exc}"
        )

    if dry_run:
        click.echo("Dry run — no changes will be made:")
    for action in actions:
        if action.startswith("WARNING"):
            click.secho(f"  {action}" if dry_run else action, err=True, fg="yellow")
        else:
            click.echo(f"  {action}" if dry_run else action)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@click.command("list")
def list_cmd() -> None:
    """List available credential helpers and their installation status.

    Shows which helpers are available, whether their launcher binary is
    present on PATH, and which registry hosts they are configured for.

    Example:

    \b
        $ cloudsmith credential-helper list
    """
    for name, cls in sorted(_INSTALLERS.items()):
        installer = cls()
        st = installer.status()
        launcher = st.get("launcher")
        hosts = st.get("hosts", [])

        click.echo(f"{name}  ({installer.summary})")
        if launcher:
            click.echo(f"  launcher : {launcher}")
        else:
            click.echo("  launcher : not installed")
        if hosts:
            click.echo(f"  hosts    : {', '.join(hosts)}")
        else:
            click.echo("  hosts    : none configured")
