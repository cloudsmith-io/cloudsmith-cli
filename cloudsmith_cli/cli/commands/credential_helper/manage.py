# Copyright 2026 Cloudsmith Ltd
"""Install/uninstall/list commands for credential helpers.

Provides ``credential-helper install``, ``credential-helper uninstall``, and
``credential-helper list`` to manage the on-PATH launcher binary and the
``config.json`` entries for each supported credential helper.
"""

from __future__ import annotations

import sys

import click

from cloudsmith_cli.credential_helpers.cargo.installer import CargoInstaller
from cloudsmith_cli.credential_helpers.generic import PartialInstallError
from cloudsmith_cli.credential_helpers.pnpm.installer import PNPMInstaller
from cloudsmith_cli.credential_helpers.terraform.installer import TerraformInstaller
from cloudsmith_cli.credential_helpers.terraform.terraformrc import (
    TerraformrcConflictError,
)

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
    "pnpm": PNPMInstaller,
    "cargo": CargoInstaller,
    "terraform": TerraformInstaller,
}


def _get_installer(name: str):
    """Return an instantiated installer for *name*, or exit with a clear error.

    Parameters
    ----------
    name:
        The helper name as supplied by the user (e.g. ``"docker"``).

    Returns
    -------
    BaseInstaller
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


def _terraform_helper_args(ctx, opts, repo: str | None = None) -> tuple[str, ...]:
    """Build the terraformrc ``args`` list from the resolved org, repo and profile.

    Baking ``--org``/``-r``/``-P`` into the block means ``terraform init`` works
    with no environment variables and no hand-edited config. Only values
    actually supplied are written, so an install without ``--org``/``--repo``/
    ``-P`` leaves ``args = []``.
    """
    args: list[str] = []
    if opts.org:
        args.extend(["--org", opts.org])
    if repo:
        args.extend(["-r", repo])
    profile = ctx.meta.get("profile")
    if profile:
        args.extend(["-P", profile])
    return tuple(args)


_REPO_FLAGS = ("-r", "--repo", "--repository")


def _terraform_next_steps(helper_args: tuple[str, ...]) -> list[str]:
    """Return the post-install guidance for the required repository.

    Terraform never tells the credentials helper which repository is being
    requested, so the helper needs the repository supplied out-of-band. If it
    was not baked into the generated ``args`` at install time, tell the user how
    to provide it: set ``CLOUDSMITH_REPO`` or add ``--repo`` to the terraformrc
    ``args``. Returns an empty list when a repository is already configured.
    """
    has_repo = any(
        a in _REPO_FLAGS or a.split("=", 1)[0] in _REPO_FLAGS for a in helper_args
    )
    if has_repo:
        return []
    return [
        (
            "Next steps: the Terraform helper requires a repository, which"
            " Terraform does not pass to credentials helpers. Provide it in one"
            " of these ways:"
        ),
        (
            "  - export CLOUDSMITH_REPO=<your-repo> in the environment that runs"
            " `terraform init`, or"
        ),
        (
            "  - add it to the args in ~/.terraformrc, e.g."
            ' args = ["--repo", "<your-repo>", ...].'
        ),
    ]


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
    help="Disable automatic discovery of custom domains.",
)
@click.option(
    "--refresh",
    is_flag=True,
    default=False,
    help="Bypass the custom-domain cache and fetch fresh data from the API.",
)
@click.option(
    "-r",
    "--repo",
    "--repository",
    "repo",
    default=None,
    help="Terraform only: bake this repository into the terraformrc `args` "
    "list (as `-r <repo>`) so `terraform init` needs no CLOUDSMITH_REPO env "
    "var. Terraform does not pass the repository to a credentials helper.",
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
    repo: str | None,
) -> None:
    """Install a credential helper launcher and configure the package manager.

    HELPER is the name of the credential helper to install (e.g. ``docker``, ``pnpm``).

    Important for pnpm: The tokenHelper directive is only honored in the
    user-level ~/.npmrc file, not in a project-level .npmrc. This is a pnpm
    security restriction. The absolute path to the launcher is automatically
    calculated and configured.

    Examples:

    \b
        # Install credential helper
        $ cloudsmith credential-helper install HELPER

    \b
        # Install with a custom domain
        $ cloudsmith credential-helper install HELPER --domain my.registry.example.com

    \b
        # Preview without making changes
        $ cloudsmith credential-helper install HELPER --dry-run

    \b
        # Disable automatic custom-domain discovery
        $ cloudsmith credential-helper install HELPER --no-discover

    \b
        # Terraform: bake the repository into the terraformrc args so
        # `terraform init` needs no CLOUDSMITH_REPO env var
        $ cloudsmith credential-helper install terraform --org acme --repo my-repo
    """
    installer = _get_installer(helper)

    install_kwargs = {
        "bin_dir": bin_dir,
        "domains": domains,
        "dry_run": dry_run,
        "discover": not no_discover,
        "refresh": refresh,
        "org": opts.org,
        "credential": opts.credential,
        "api_host": opts.api_host,
    }

    # Terraform bakes the resolved org/profile into the terraformrc `args` list
    # so `terraform init` needs neither env vars nor a hand-edited config. The
    # wrapper forwards these to the CLI ahead of the hostname at call time.
    if helper == "terraform":
        install_kwargs["helper_args"] = _terraform_helper_args(ctx, opts, repo)

    try:
        actions = installer.install(**install_kwargs)
    except TerraformrcConflictError as exc:
        raise click.ClickException(str(exc))
    except OSError as exc:
        raise click.ClickException(
            f"Failed to install {helper!r} credential helper: {exc}"
        )
    except PartialInstallError as exc:
        actions = exc.actions
        ec = exc.exit_code
    else:
        ec = 0

    use_stderr = utils.should_use_stderr(opts)
    warnings = [a for a in actions if a.startswith("WARNING")]
    normal = [a for a in actions if not a.startswith("WARNING")]

    next_steps: list[str] = []
    if helper == "terraform":
        next_steps = _terraform_next_steps(install_kwargs.get("helper_args", ()))

    data = {
        "helper": helper,
        "dry_run": dry_run,
        "actions": normal,
        "warnings": warnings,
        "next_steps": next_steps,
    }
    if utils.maybe_print_as_json(opts, data):
        sys.exit(ec)

    if dry_run:
        click.echo("Dry run — no changes will be made:", err=use_stderr)
    for action in normal:
        click.echo(f"  {action}" if dry_run else action, err=use_stderr)
    for warning in warnings:
        click.secho(f"  {warning}" if dry_run else warning, err=True, fg="yellow")
    for line in next_steps:
        click.secho(line, err=use_stderr, fg="cyan")
    sys.exit(ec)


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
