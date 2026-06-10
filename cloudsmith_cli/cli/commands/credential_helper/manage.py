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
from ... import utils
from ...decorators import (
    common_api_auth_options,
    common_cli_config_options,
    common_cli_output_options,
    resolve_credentials,
)

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
@common_cli_config_options
@common_cli_output_options
@common_api_auth_options
@resolve_credentials
@click.pass_context
def install_cmd(
    ctx,
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

    use_stderr = utils.should_use_stderr(opts)
    warnings = [a for a in actions if a.startswith("WARNING")]
    normal = [a for a in actions if not a.startswith("WARNING")]
    data = {
        "helper": helper,
        "dry_run": dry_run,
        "actions": normal,
        "warnings": warnings,
    }
    if utils.maybe_print_as_json(opts, data):
        return

    if dry_run:
        click.echo("Dry run — no changes will be made:", err=use_stderr)
    for action in normal:
        click.echo(f"  {action}" if dry_run else action, err=use_stderr)
    for warning in warnings:
        click.secho(f"  {warning}" if dry_run else warning, err=True, fg="yellow")


# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------


@click.command("uninstall")
@click.argument("helper")
@click.option(
    "--bin-dir", default=None, help="Directory where the launcher binary was installed."
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be done without making any changes.",
)
@common_cli_config_options
@common_cli_output_options
@click.pass_context
def uninstall_cmd(ctx, opts, helper: str, bin_dir: str | None, dry_run: bool) -> None:
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
        actions = installer.uninstall(bin_dir=bin_dir, dry_run=dry_run)
    except OSError as exc:
        raise click.ClickException(
            f"Failed to uninstall {helper!r} credential helper: {exc}"
        )

    use_stderr = utils.should_use_stderr(opts)
    warnings = [a for a in actions if a.startswith("WARNING")]
    normal = [a for a in actions if not a.startswith("WARNING")]
    data = {
        "helper": helper,
        "dry_run": dry_run,
        "actions": normal,
        "warnings": warnings,
    }
    if utils.maybe_print_as_json(opts, data):
        return

    if dry_run:
        click.echo("Dry run — no changes will be made:", err=use_stderr)
    for action in normal:
        click.echo(f"  {action}" if dry_run else action, err=use_stderr)
    for warning in warnings:
        click.secho(f"  {warning}" if dry_run else warning, err=True, fg="yellow")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@click.command("list")
@common_cli_config_options
@common_cli_output_options
@click.pass_context
def list_cmd(ctx, opts) -> None:
    """List available credential helpers and their installation status.

    Shows which helpers are available, whether their launcher binary is
    present on PATH, and which registry hosts they are configured for.

    Example:

    \b
        $ cloudsmith credential-helper list
    """
    use_stderr = utils.should_use_stderr(opts)

    data = []
    for name, cls in sorted(_INSTALLERS.items()):
        installer = cls()
        st = installer.status()
        data.append(
            {
                "helper": name,
                "summary": installer.summary,
                "launcher": st.get("launcher"),
                "hosts": st.get("hosts", []),
            }
        )

    if utils.maybe_print_as_json(opts, data):
        return

    for entry in data:
        name = entry["helper"]
        launcher = entry["launcher"]
        hosts = entry["hosts"]
        summary = entry["summary"]

        click.echo(f"{name}  ({summary})", err=use_stderr)
        if launcher:
            click.echo(f"  launcher : {launcher}", err=use_stderr)
        else:
            click.echo("  launcher : not installed", err=use_stderr)
        if hosts:
            click.echo(f"  hosts    : {', '.join(hosts)}", err=use_stderr)
        else:
            click.echo("  hosts    : none configured", err=use_stderr)
