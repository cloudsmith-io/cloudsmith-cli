# Copyright 2026 Cloudsmith Ltd
"""List the hosts Cloudsmith can authenticate: built-in and custom domains.

The built-in ``*.cloudsmith.io`` service hosts ship with the CLI so that every
consumer shares one authoritative table; custom domains cannot be inferred, so
discovering them requires an API lookup.
"""

from __future__ import annotations

import json
import os

import click
from click.core import ParameterSource

from ...core.api.exceptions import ApiException
from ...core.pagination import PageInfo
from ...credential_helpers.custom_domains import (
    get_custom_domains,
    order_by_precedence,
    read_all_cached_domains,
)
from ...credential_helpers.default_domains import (
    DomainType,
    format_for_backend_kind,
    load_default_domains,
    untrusted_config_declares_domains,
)
from .. import command
from ..config import get_default_config_path
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


def _custom_entries(records) -> list[dict]:
    """Render custom-domain records as document entries, in the order given."""
    return [
        {
            "host": record.host,
            "format": format_for_backend_kind(record.backend_kind),
            "type": "custom",
            "domain_type": record.domain_type.value,
            "org": record.org,
            "repository": record.repository,
            "primary": record.primary,
            "created_at": record.created_at,
        }
        for record in records
    ]


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
    help="Bypass the custom-domain cache and fetch fresh data from the API.",
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
    help="Only list hosts with this purpose: download, upload, or native_api. "
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

    Machine-readable output for programmatic consumers. It lists the built-in
    ``*.cloudsmith.io`` service hosts alongside custom domains, with ``type``
    distinguishing ``default`` from ``custom`` and ``domain_type`` saying what
    each host is for: ``download``, ``upload``, or ``native_api`` for a host
    speaking one package format's own protocol. An organisation's own custom
    domains are listed ahead of the built-in hosts, which serve as the
    fallback. Only usable hosts are listed: a custom domain that is disabled or
    not yet validated serves nothing, so it is left out rather than offered as
    somewhere to publish to. Check it in the Cloudsmith UI if one you expect is
    missing here.

    Built-in hosts are always listed and need no organisation or authentication.
    An organisation from ``--org``, CLOUDSMITH_ORG or ``org`` in ``config.ini``
    adds its custom domains, and a failed lookup exits non-zero rather than
    rendering as "no domains". With no organisation the command lists whatever
    earlier runs cached and makes no API call; ``--refresh`` bypasses that cache
    for a configured organisation.

    Where two custom domains could serve the same request Cloudsmith picks the
    one bound to the repository in hand, then ``primary`` over secondary, then
    the oldest — so ``created_at`` is reported to make that order reproducible.
    The custom domains are always listed in that order, so the first is the one
    Cloudsmith would bind; ``--repo`` is what lets the repository-bound hosts
    take part in it.

    Results support the same --page/--page-size (-p/-l) options as other
    `list` commands, selecting a page of the combined, filtered list. Unlike
    those commands, this one defaults to --page-all (--show-all): the
    combined list is small and built from a local cache rather than a live
    paginated endpoint, so there is no benefit to hiding entries by default.
    Passing --page or --page-size switches to paged output.

    Output (stdout):
        JSON: {"version": 1, "domains": [{"host": ..., "format": ...,
        "type": ..., "domain_type": ..., "org": ..., "repository": ...,
        "primary": ..., "created_at": ...}], "meta": {"pagination": {...}}}

        "meta" is only present when the result is paginated (i.e. not
        --page-all), and mirrors the pagination metadata other `list`
        commands emit for `-F json`.

    Examples:

    \b
        # List built-in hosts plus any custom domains already cached
        $ cloudsmith domains list

    \b
        # List built-in hosts plus an organisation's custom domains
        $ cloudsmith domains list --org my-org

    \b
        # The hosts usable for one repository, most-preferred first
        $ cloudsmith domains list --org my-org --repo my-repo --format maven

    \b
        # Where to upload to
        $ cloudsmith domains list --org my-org --domain-type upload
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

    explicit_config = ctx.meta.get("config_file")
    if explicit_config and os.path.isdir(explicit_config):
        explicit_config = os.path.join(explicit_config, "config.ini")

    if explicit_config is None and untrusted_config_declares_domains():
        click.secho(
            "Warning: ignoring [domains] section in ./config.ini -- config.ini "
            "in the current directory is untrusted. Put it in "
            f"{get_default_config_path()} or ~/.cloudsmith instead.",
            fg="yellow",
            err=True,
        )

    wanted_format = _label(format_)
    wanted_type = _label(domain_type)
    repository = _label(repo)

    default_entries = [
        {
            "host": domain.host,
            "format": domain.format_label,
            "type": "default",
            "domain_type": domain.domain_type.value,
            "org": None,
            "repository": None,
            "primary": True,
            "created_at": None,
        }
        for domain in load_default_domains(config_path=explicit_config)
        if _serves_format(domain.format_label, wanted_format)
        and _is_domain_type(domain.domain_type, wanted_type)
    ]

    org = opts.org
    if org:
        try:
            records = get_custom_domains(
                org,
                credential=opts.credential,
                api_host=opts.api_host,
                refresh=refresh,
                strict=True,
                configure_api=False,
            )
        except ApiException as exc:
            raise click.ClickException(
                f"Failed to fetch custom domains for {org!r}: {exc}"
            ) from exc
    else:
        if refresh:
            click.secho(
                "Warning: --refresh needs an organisation to fetch from, so the "
                "cached custom domains below are unchanged. Set --org, "
                "CLOUDSMITH_ORG or org in config.ini.",
                fg="yellow",
                err=True,
            )
        records = read_all_cached_domains()

    records = [
        record
        for record in records
        if _serves_format(format_for_backend_kind(record.backend_kind), wanted_format)
        and _is_domain_type(record.domain_type, wanted_type)
        and record.is_active
        and (repository is None or record.serves_repository(repository))
    ]
    records = sorted(
        order_by_precedence(records, repository), key=lambda record: record.org
    )

    data = _custom_entries(records) + default_entries

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
