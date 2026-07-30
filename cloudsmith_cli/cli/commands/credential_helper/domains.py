# Copyright 2026 Cloudsmith Ltd
"""List the hosts Cloudsmith can authenticate: built-in and custom domains.

The built-in ``*.cloudsmith.io`` service hosts ship with the CLI so that every
consumer shares one authoritative table; custom domains are the hosts a
credential-helper consumer cannot infer on its own, since discovering them
requires an API lookup.
"""

from __future__ import annotations

import json
import os

import click

from ....credential_helpers.backends import BackendKind
from ....credential_helpers.custom_domains import get_custom_domains
from ....credential_helpers.default_domains import (
    load_default_domains,
    untrusted_config_declares_domains,
)
from ...config import get_default_config_path
from ...decorators import (
    common_api_auth_options,
    common_cli_config_options,
    resolve_credentials,
)

# Bump only for a breaking change to the document shape. Consumers are expected
# to refuse a version they do not recognise.
PROTOCOL_VERSION = 1


def format_name(backend_kind: int | None) -> str:
    """Return a human-readable package format for a backend kind value.

    A download-CDN domain has no backend kind and renders as ``-``.  A value
    outside :class:`BackendKind` renders as itself: the enum is a
    hand-maintained mirror of the server-side one, so a newly added server
    format must not break this command.
    """
    if backend_kind is None:
        return "-"

    try:
        return BackendKind(backend_kind).name.lower()
    except ValueError:
        return str(backend_kind)


@click.command("domains")
@click.option(
    "--org",
    default=None,
    help="Cloudsmith organisation slug (defaults to CLOUDSMITH_ORG).",
)
@click.option(
    "--custom-only",
    is_flag=True,
    default=False,
    help="List only the organisation's custom domains, omitting the built-in hosts.",
)
@common_cli_config_options
@common_api_auth_options
@resolve_credentials
@click.pass_context
def domains_cmd(ctx, opts, org: str | None, custom_only: bool) -> None:
    """Emit the Cloudsmith hosts and their package formats as JSON.

    Emits machine-readable JSON for programmatic consumers -- such as a
    keyring backend that shells out to the CLI and parses stdout -- listing
    the built-in Cloudsmith service hosts (``*.cloudsmith.io``) alongside the
    organisation's custom domains. These are the hosts a credential-helper
    consumer cannot infer on its own, since discovering them requires an API
    lookup. Each entry's ``type`` field distinguishes ``default`` from
    ``custom``. Every domain is included, even custom ones that are disabled
    or not yet validated, so a domain that is present but not working is
    visible rather than silently absent. Consumers that need a usable host
    should filter on both ``enabled`` and ``validated``.

    Listing the built-in hosts needs no organisation. Custom domains do, so
    ``--org``/``CLOUDSMITH_ORG`` is only required together with
    ``--custom-only``, or to see custom domains at all.

    Output (stdout):
        JSON: {"version": 1, "domains": [{"host": ..., "format": ...,
        "backend_kind": ..., "enabled": ..., "validated": ..., "type": ...}]}

    Examples:

    \b
        # List the built-in hosts, no organisation required
        $ cloudsmith credential-helper domains

    \b
        # List built-in hosts plus an organisation's custom domains
        $ cloudsmith credential-helper domains --org my-org

    \b
        # List only the organisation's custom domains
        $ cloudsmith credential-helper domains --org my-org --custom-only
    """
    org = org or os.environ.get("CLOUDSMITH_ORG", "").strip() or None
    if custom_only and not org:
        raise click.ClickException(
            "No organisation specified. Use --org or set CLOUDSMITH_ORG."
        )

    if untrusted_config_declares_domains():
        click.secho(
            "Warning: ignoring [domains] section in ./config.ini -- config.ini "
            "in the current directory is untrusted. Put it in "
            f"{get_default_config_path()} or ~/.cloudsmith instead.",
            fg="yellow",
            err=True,
        )

    explicit_config = ctx.meta.get("config_file")
    if explicit_config and os.path.isdir(explicit_config):
        explicit_config = os.path.join(explicit_config, "config.ini")

    default_data = (
        []
        if custom_only
        else [
            {
                "host": domain.host,
                "format": domain.format_label,
                "backend_kind": domain.backend_kind,
                "enabled": True,
                "validated": True,
                "type": "default",
            }
            for domain in load_default_domains(config_path=explicit_config)
        ]
    )

    custom_data = []
    if org:
        api_key = opts.credential.api_key if opts.credential else None
        auth_type = (
            getattr(opts.credential, "auth_type", "api_key")
            if opts.credential
            else "api_key"
        )

        try:
            records = get_custom_domains(
                org,
                api_key=api_key,
                auth_type=auth_type,
                api_host=opts.api_host,
            )
        except Exception as exc:  # pylint: disable=broad-except
            raise click.ClickException(
                f"Failed to fetch custom domains for {org!r}: {exc}"
            ) from exc

        custom_data = [
            {
                "host": record.host,
                "format": format_name(record.backend_kind),
                "backend_kind": record.backend_kind,
                "enabled": record.enabled,
                "validated": record.validated,
                "type": "custom",
            }
            for record in sorted(records, key=lambda record: record.host)
        ]

    data = default_data + custom_data

    click.echo(json.dumps({"version": PROTOCOL_VERSION, "domains": data}))
