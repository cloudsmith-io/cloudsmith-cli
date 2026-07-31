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

from ....credential_helpers.custom_domains import (
    get_custom_domains,
    read_all_cached_domains,
)
from ....credential_helpers.default_domains import (
    domain_type_for_backend_kind,
    format_for_backend_kind,
    load_default_domains,
    untrusted_config_declares_domains,
)
from ...config import get_default_config_path
from ...decorators import (
    common_api_auth_options,
    common_cli_config_options,
    resolve_credentials,
)

PROTOCOL_VERSION = 1


def _custom_entries(records) -> list[dict]:
    """Render custom-domain records as document entries."""
    return [
        {
            "host": record.host,
            "format": format_for_backend_kind(record.backend_kind),
            "enabled": record.enabled,
            "validated": record.validated,
            "type": "custom",
            "domain_type": domain_type_for_backend_kind(record.backend_kind).value,
            "org": record.org,
            "repository": record.repository,
        }
        for record in sorted(records, key=lambda record: (record.org, record.host))
    ]


@click.command("domains")
@click.option(
    "--refresh",
    is_flag=True,
    default=False,
    help="Bypass the custom-domain cache and fetch fresh data from the API.",
)
@common_cli_config_options
@common_api_auth_options
@resolve_credentials
@click.pass_context
def domains_cmd(ctx, opts, refresh: bool) -> None:
    """Emit the Cloudsmith hosts and their package formats as JSON.

    Emits machine-readable JSON for programmatic consumers listing the
    built-in Cloudsmith service hosts (``*.cloudsmith.io``) alongside custom
    domains. Each entry's ``type`` field distinguishes ``default`` from
    ``custom``, and ``domain_type`` says what the host is for: ``download``,
    ``upload``, or ``native_api`` for a host speaking one package format's own
    protocol. Every domain is included, even custom ones that are disabled or
    not yet validated, so a domain that is present but not working is visible
    rather than silently absent. Consumers that need a usable host should
    filter on both ``enabled`` and ``validated``.

    The built-in hosts are always listed and need no organisation or
    authentication. When an organisation is configured - CLOUDSMITH_ORG, or
    ``oidc_org`` in ``config.ini`` - its custom domains are looked up, and a
    failed lookup exits non-zero rather than being rendered as "no domains".
    With none configured, the command instead lists the custom domains any
    earlier run already cached and makes no API call at all: there is
    deliberately no lookup of which organisations the caller belongs to, since
    that would cost one API call per organisation on every run. A custom
    entry's ``org`` and ``repository`` fields say which organisation it
    belongs to and, when scoped to one, which repository - built-in entries
    carry ``null`` for both. Pass ``--refresh`` to bypass the cache and fetch
    fresh data from the API for a configured organisation.

    Output (stdout):
        JSON: {"version": 1, "domains": [{"host": ..., "format": ...,
        "enabled": ..., "validated": ..., "type": ..., "domain_type": ...,
        "org": ..., "repository": ...}]}

    Examples:

    \b
        # List built-in hosts plus any custom domains already cached
        $ cloudsmith credential-helper domains

    \b
        # List built-in hosts plus an organisation's custom domains
        $ CLOUDSMITH_ORG=my-org cloudsmith credential-helper domains
    """
    explicit_config = ctx.meta.get("config_file")
    if explicit_config and os.path.isdir(explicit_config):
        explicit_config = os.path.join(explicit_config, "config.ini")

    # An explicit --config-file is trusted and read directly, so the
    # untrusted-cwd scan does not apply — warning about the very file the
    # user passed would claim the opposite of what happens.
    if explicit_config is None and untrusted_config_declares_domains():
        click.secho(
            "Warning: ignoring [domains] section in ./config.ini -- config.ini "
            "in the current directory is untrusted. Put it in "
            f"{get_default_config_path()} or ~/.cloudsmith instead.",
            fg="yellow",
            err=True,
        )

    data = [
        {
            "host": domain.host,
            "format": domain.format_label,
            "enabled": True,
            "validated": True,
            "type": "default",
            "domain_type": domain.domain_type.value,
            "org": None,
            "repository": None,
        }
        for domain in load_default_domains(config_path=explicit_config)
    ]

    org = opts.oidc_org
    if org:
        try:
            records = get_custom_domains(
                org,
                credential=opts.credential,
                api_host=opts.api_host,
                refresh=refresh,
                strict=True,
            )
        except Exception as exc:  # pylint: disable=broad-except
            # Presentation boundary: a named organisation that cannot be read
            # is the user's error, and must not be rendered as "no domains".
            raise click.ClickException(
                f"Failed to fetch custom domains for {org!r}: {exc}"
            ) from exc
    else:
        # No organisation named: list what earlier runs cached rather than
        # spending an API call per organisation to rediscover it.
        records = read_all_cached_domains()

    data.extend(_custom_entries(records))

    click.echo(json.dumps({"version": PROTOCOL_VERSION, "domains": data}))
