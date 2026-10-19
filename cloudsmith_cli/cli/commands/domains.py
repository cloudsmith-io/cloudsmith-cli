# Copyright 2026 Cloudsmith Ltd
"""List the hosts Cloudsmith can authenticate: Cloudsmith-owned and custom domains.

The configured API host lists the domains that serve a Workspace, so the CLI
holds no table of Cloudsmith hostnames and works against any Cloudsmith.
"""

from __future__ import annotations

import json

import click
from click.core import ParameterSource

from ...core.api.exceptions import ApiException
from ...core.api.orgs import list_orgs
from ...core.pagination import PageInfo
from ...credential_helpers.domains import (
    DomainType,
    WorkspaceDomain,
    get_workspace_domains,
    read_all_cached_domains,
)
from .. import command
from ..decorators import (
    common_api_auth_options,
    common_cli_config_options,
    common_cli_list_options,
    initialise_api,
)
from .main import main

PROTOCOL_VERSION = 1


def _label(value: str | None) -> str | None:
    """Normalise a filter value for comparison, or None if it is empty."""
    return (value or "").strip().lower() or None


def _serves_format(entry_format: str | None, wanted: str | None) -> bool:
    """Whether an entry's format satisfies a ``--format`` filter."""
    return wanted is None or entry_format is None or entry_format == wanted


def _is_domain_type(domain_type: DomainType, wanted: str | None) -> bool:
    """Whether a host's purpose satisfies a ``--domain-type`` filter."""
    return wanted is None or domain_type.value == wanted


def _entry(record: WorkspaceDomain) -> dict:
    """Render a domain record as a document entry."""
    return {
        "host": record.host,
        "format": record.format_label,
        "type": "custom" if record.is_custom else "default",
        "domain_type": record.domain_type.value,
        "workspace": record.workspace,
        "org": record.workspace,
        "repository": record.repository,
        "primary": None,
        "created_at": None,
    }


def _merge_cached(records: list[WorkspaceDomain]) -> list[WorkspaceDomain]:
    """Merge the cached answers for several Workspaces into one list.

    No single API order covers several Workspaces, so custom domains are
    grouped by Workspace ahead of the Cloudsmith-owned ones. Each group keeps
    the API order. Every cached answer repeats the Cloudsmith-owned domains,
    so each one is listed once.
    """
    custom = [record for record in records if record.is_custom]
    cloudsmith_owned = [record for record in records if not record.is_custom]
    return sorted(custom, key=lambda record: record.workspace or "") + list(
        dict.fromkeys(cloudsmith_owned)
    )


def _member_workspace(opts) -> str | None:
    """Return a Workspace that the credential is a member of, or None."""
    if opts.credential is None:
        return None
    workspaces = list_orgs(page=1, page_size=1)
    return workspaces[0]["slug"] if workspaces else None


def _get_domains(opts, refresh: bool) -> list[WorkspaceDomain]:
    """Get the domains of the configured Workspace, or of a cached or member one.

    Every Workspace answer holds the Cloudsmith-owned domains. Without a
    configured Workspace, the cached answers supply them, or else the answer
    for any Workspace that the credential is a member of.
    """
    workspace = opts.org
    if not workspace:
        cached = read_all_cached_domains(opts.api_host)
        if cached:
            if refresh:
                click.secho(
                    "Warning: --refresh needs a Workspace to fetch from, so the "
                    "cached domains below are unchanged. Set --workspace, "
                    "CLOUDSMITH_WORKSPACE, or workspace in config.ini.",
                    fg="yellow",
                    err=True,
                )
            return _merge_cached(cached)
        try:
            workspace = _member_workspace(opts)
        except ApiException as exc:
            raise click.ClickException(
                f"Failed to find a Workspace to fetch domains for: {exc}"
            ) from exc
        if workspace is None:
            return []

    try:
        return get_workspace_domains(
            workspace,
            credential=opts.credential,
            api_host=opts.api_host,
            refresh=refresh,
            strict=True,
            configure_api=False,
        )
    except ApiException as exc:
        raise click.ClickException(
            f"Failed to fetch domains for {workspace!r}: {exc}"
        ) from exc


@main.group(name="domains", cls=command.AliasGroup, aliases=["domain"])
def domains_():
    """
    Inspect the Cloudsmith domains the CLI can authenticate.

    See the help for subcommands for more information on each.
    """


@domains_.command(name="list", aliases=["ls"])
@click.option(
    "--refresh",
    is_flag=True,
    default=False,
    help="Bypass the domain cache and fetch fresh data from the API.",
)
@click.option(
    "--format",
    "format_",
    default=None,
    help="Only list hosts usable for this package format. Hosts that serve no "
    "single format (the download CDN, the generic upload endpoint) serve every "
    "format and are always listed.",
)
@click.option(
    "--domain-type",
    "domain_type",
    default=None,
    help="Only list hosts with this purpose: download, upload, cloudsmith_api, "
    "or native_api. "
    "Every host has exactly one, so this is an exact match.",
)
@click.option(
    "--repo",
    "--repository",
    "repo",
    default=None,
    help="Only list hosts usable for this repository, most-preferred first. "
    "Drops custom domains bound to a different repository.",
)
@common_cli_config_options
@common_cli_list_options
@common_api_auth_options
@initialise_api
@click.pass_context
def list_domains(  # pylint: disable=too-many-arguments
    ctx,
    opts,
    refresh: bool,
    format_: str | None,
    domain_type: str | None,
    repo: str | None,
    page: int,
    page_size: int,
    page_all: bool,
) -> None:
    """Emit the Cloudsmith hosts and their package formats as JSON.

    Machine-readable output for programmatic consumers. The configured API host
    lists the domains that serve a Workspace, so the hosts match whichever
    Cloudsmith the CLI talks to. ``type`` distinguishes Cloudsmith-owned
    (``default``) from ``custom`` domains, and ``domain_type`` says what each
    host is for: ``download``, ``upload``, ``cloudsmith_api``, or
    ``native_api`` for a host speaking one package format's own protocol. Only
    usable hosts are listed: the API leaves out a custom domain that is
    disabled or not yet validated. Check it in the Cloudsmith UI if one you
    expect is missing here.

    The lookup uses the Workspace from ``--workspace``, CLOUDSMITH_WORKSPACE,
    or ``workspace`` in ``config.ini``, and needs authentication as a member
    of it. A failed lookup exits non-zero rather than rendering as "no
    domains". With no Workspace the command lists whatever earlier runs cached
    for the configured API host. If nothing is cached, it fetches the domains
    of a Workspace that the credential is a member of, which include all the
    Cloudsmith-owned hosts. ``--refresh`` bypasses the cache for a configured
    Workspace.

    Hosts are listed in the API's preference order: domains restricted to a
    repository, then the Workspace's own, then the Cloudsmith-owned ones.
    Within each group the primary domain comes first, then the oldest, so the
    first host usable for a request is the one Cloudsmith would choose.
    ``--repo`` drops the domains restricted to other repositories.

    Results support the same --page/--page-size (-p/-l) options as other
    `list` commands, selecting a page of the combined, filtered list. Unlike
    those commands, this one defaults to --page-all (--show-all): the
    combined list is small and built from a local cache rather than a live
    paginated endpoint, so there is no benefit to hiding entries by default.
    Passing --page or --page-size switches to paged output.

    \b
    Output (stdout):
        JSON: {"version": 1, "domains": [{"host": ..., "format": ...,
        "type": ..., "domain_type": ..., "workspace": ..., "org": ...,
        "repository": ..., "primary": null, "created_at": null}],
        "meta": {"pagination": {...}}}

        "org" repeats "workspace". The API does not give "primary" and
        "created_at", so they are always null. Use the list order instead.

        "meta" is only present when the result is paginated (i.e. not
        --page-all), and mirrors the pagination metadata other `list`
        commands emit for `-F json`.

    Examples:

    \b
        # List the Cloudsmith-owned hosts and any cached custom domains
        $ cloudsmith domains list

    \b
        # List the domains that serve a Workspace
        $ cloudsmith domains list --workspace my-workspace

    \b
        # The hosts usable for one repository, most-preferred first
        $ cloudsmith domains list --workspace my-workspace --repo my-repo --format maven

    \b
        # Where to upload to
        $ cloudsmith domains list --workspace my-workspace --domain-type upload
    """
    if not page_all:
        explicit_sources = {
            src
            for src in (
                ParameterSource.COMMANDLINE,
                ParameterSource.ENVIRONMENT,
                getattr(ParameterSource, "PROMPT", None),
            )
            if src is not None
        }
        page_explicit = ctx.get_parameter_source("page") in explicit_sources
        page_size_explicit = ctx.get_parameter_source("page_size") in explicit_sources
        if not page_explicit and not page_size_explicit:
            # Unlike other `list` commands, domains list defaults to showing
            # everything: the combined list is small and built from a local
            # cache, so paging by default would hide entries for no benefit.
            page_all = True

    wanted_format = _label(format_)
    wanted_type = _label(domain_type)
    repository = _label(repo)

    records = [
        record
        for record in _get_domains(opts, refresh)
        if _serves_format(record.format_label, wanted_format)
        and _is_domain_type(record.domain_type, wanted_type)
        and (repository is None or record.serves_repository(repository))
    ]
    data = [_entry(record) for record in records]

    document = {"version": PROTOCOL_VERSION, "domains": data}

    if not page_all:
        if page < 1 or page_size < 1:
            raise click.UsageError("--page and --page-size must be positive.")

        total = len(data)
        start = (page - 1) * page_size
        page_info = PageInfo()
        page_info.count = total
        page_info.page = page
        page_info.page_size = page_size
        page_info.page_total = -(-total // page_size) or 1

        document["domains"] = data[start : start + page_size]
        document["meta"] = {
            "pagination": page_info.as_dict(num_results=len(document["domains"]))
        }

    click.echo(json.dumps(document))
