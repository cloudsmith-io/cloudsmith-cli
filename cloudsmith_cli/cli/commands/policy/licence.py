# -*- coding: utf-8 -*-
"""CLI/Commands - create, retrieve, update or delete licence policies."""
from __future__ import absolute_import, print_function, unicode_literals

import json

import click
import six

from ....core.api import orgs as api
from ... import command, decorators, utils, validators
from ...exceptions import handle_api_exceptions
from ...utils import fmt_bool, fmt_datetime, maybe_spinner
from .command import policy


def print_licence_policies(policies):
    """Print licence policies as a table or output in another format."""

    headers = [
        "Name",
        "Description",
        "Allow Unknown Licences",
        "Quarantine On Violation",
        "SPDX Identifiers",
        "Created",
        "Updated",
        "Identifier",
    ]

    rows = [
        [
            click.style(policy["name"], fg="cyan"),
            click.style(policy["description"], fg="yellow"),
            click.style(fmt_bool(policy["allow_unknown_licenses"]), fg="yellow"),
            click.style(fmt_bool(policy["on_violation_quarantine"]), fg="yellow"),
            click.style(six.text_type(policy["spdx_identifiers"]), fg="blue"),
            click.style(fmt_datetime(policy["created_at"]), fg="blue"),
            click.style(fmt_datetime(policy["updated_at"]), fg="blue"),
            click.style(policy["slug_perm"], fg="green"),
        ]
        for policy in policies
    ]

    click.echo()
    utils.pretty_print_table(headers, rows)
    click.echo()

    num_results = len(rows)
    list_suffix = "licence polic%s" % ("y" if num_results == 1 else "ies")
    utils.pretty_print_list_info(num_results=num_results, suffix=list_suffix)


@policy.group(cls=command.AliasGroup, name="licence", aliases=[])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def licence(*args, **kwargs):
    """
    Manage licence policies for an organization.

    See the help for subcommands for more information on each.
    """


@licence.command(name="list", aliases=["ls"])
@decorators.common_cli_config_options
@decorators.common_cli_list_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner", metavar="OWNER", callback=validators.validate_owner, required=True
)
@click.pass_context
def ls(ctx, opts, owner, page, page_size):
    """
    List licence policies.

    This requires appropriate permissions for the owner (a member of the
    organisation and a valid API key).

    - OWNER: Specify the OWNER namespace (i.e. org)

      Example: 'your-org'

    Full CLI example:

      $ cloudsmith policy licence list your-org
    """
    owner = owner[0]

    # Use stderr for messages if the output is something else (e.g.  # JSON)
    use_stderr = opts.output != "pretty"

    click.echo("Getting licence policies ... ", nl=False, err=use_stderr)

    context_msg = "Failed to get licence policies!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            policies, page_info = api.list_licence_policies(
                owner=owner, page=page, page_size=page_size
            )

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, policies, page_info):
        return

    print_licence_policies(policies)


@licence.command(aliases=["new"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument("owner", default=None, required=True)
@click.argument("policy_config_file", type=click.File("rb"), required=True)
@click.pass_context
def create(ctx, opts, owner, policy_config_file):
    """
    Create a new licence policy in a namespace.

    - OWNER: Specify the OWNER namespace (i.e. user or org) where you want
      to create a licence policy.

        Example: 'your-org'

    - POLICY_CONFIG_FILE: Config file specifying the settings for the
      licence policy to be created.

        \b
        Example:
        {
          "name": "your-licence-policy",
          "description": "your licence policy description",
          "spdx_identifiers" : ["your_licences"],
          "allow_unknown_licences": false,
          "quarantine_on_violation": true
        }

    Full CLI example:

      $ cloudsmith policy licence create your-org policy-config-file.json
    """
    # Use stderr for messages if the output is something else (e.g. JSON)
    use_stderr = opts.output != "pretty"
    policy_config = json.load(policy_config_file)

    policy_name = policy_config.get("name", None)
    if policy_name is None:
        raise click.BadParameter(
            "Name is a required field for creating a licence policy.", param="name"
        )

    spdx_identifiers = policy_config.get("spdx_identifiers", None)
    if spdx_identifiers is None:
        raise click.BadParameter(
            "SPDX Identifiers is a required field for creating a licence policy.",
            param="spdx_identifiers",
        )

    if len(spdx_identifiers) > len(set(spdx_identifiers)):
        raise click.BadParameter(
            "SPDX Identifiers must be unique.", param="spdx_identifiers"
        )

    click.secho(
        "Creating %(name)s licence policy for the %(owner)s namespace ..."
        % {
            "name": click.style(policy_name, bold=True),
            "owner": click.style(owner, bold=True),
        },
        nl=False,
        err=use_stderr,
    )

    # Convert `allow_unknown_licences` to `allow_unknown_licenses` (avoiding license keyword)
    if "allow_unknown_licences" in policy_config:
        policy_config["allow_unknown_licenses"] = policy_config.pop(
            "allow_unknown_licences"
        )

    context_msg = "Failed to create the licence policy!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            policies = [api.create_licence_policy(owner, policy_config)]

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, policies):
        return

    print_licence_policies(policies)


@licence.command()
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument("owner", default=None, required=True)
@click.argument("identifier", default=None, required=True)
@click.argument("policy_config_file", type=click.File("rb"), required=True)
@click.pass_context
def update(ctx, opts, owner, identifier, policy_config_file):
    """
    Update a licence policy.

    - OWNER: Specify the OWNER namespace (i.e. user or org) where you want
      to update a licence policy.

        Example: 'your-org'

    - IDENTIFIER: Specify the licence policy IDENTIFIER (i.e. slug_perm)
      for the licence policy which you wish to update.

        Example: 'your-licence-policy'

    - POLICY_CONFIG_FILE: Config file specifying the settings for the
      licence policy to be updated.

        \b
        Example:
        {
          "name": "your-licence-policy",
          "description": "your licence policy description",
          "spdx_identifiers" : ["your_licences"],
          "allow_unknown_licences": false,
          "quarantine_on_violation": true
        }

    Full CLI example:

      $ cloudsmith policy licence update your-org your-licence-policy policy-config-file.json
    """
    # Use stderr for message if the output is something else (e.g. JSON)
    use_stderr = opts.output != "pretty"

    policy_config = json.load(policy_config_file)

    click.secho(
        "Updating %(slug_perm)s licence policy in the %(owner)s namespace ..."
        % {
            "slug_perm": click.style(identifier, bold=True),
            "owner": click.style(owner, bold=True),
        },
        nl=False,
        err=use_stderr,
    )

    spdx_identifiers = policy_config.get("spdx_identifiers", None)
    if len(spdx_identifiers) > len(set(spdx_identifiers)):
        raise click.BadParameter(
            "SPDX Identifiers must be unique.", param="spdx_identifiers"
        )

    # Convert `allow_unknown_licences` to `allow_unknown_licenses` (avoiding license keyword)
    if "allow_unknown_licences" in policy_config:
        policy_config["allow_unknown_licenses"] = policy_config.pop(
            "allow_unknown_licences"
        )

    context_msg = "Failed to update the licence policy!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            policies = [api.update_licence_policy(owner, identifier, policy_config)]

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, policies):
        return

    print_licence_policies(policies)


@licence.command(aliases=["rm"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument("owner", metavar="OWNER")
@click.argument("identifier", default=None, required=True)
@click.option(
    "-y",
    "--yes",
    default=False,
    is_flag=True,
    help="Assume yes as default answer to questions (this is dangerous!)",
)
@click.pass_context
def delete(ctx, opts, owner, identifier, yes):
    """
    Delete a licence policy from a namespace.

    - OWNER: Specify the OWNER namespace (i.e. org).

        Example: 'your-org'

    - IDENTIFIER: Specify the licence policy IDENTIFIER (i.e. slug_perm)
      for the licence policy which you wish to delete.

        Example: 'your-licence-policy'

    Full CLI example:

      $ cloudsmith policy licence delete your-org your-licence-policy
    """

    delete_args = {
        "namespace": click.style(owner, bold=True),
        "slug_perm": click.style(identifier, bold=True),
    }

    prompt = (
        "delete the %(slug_perm)s licence policy from the %(namespace)s namespace"
        % delete_args
    )

    if not utils.confirm_operation(prompt, assume_yes=yes):
        return

    click.secho(
        "Deleting %(slug_perm)s from the %(namespace)s namespace ... " % delete_args,
        nl=False,
    )

    context_msg = "Failed to delete the licence policy!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            api.delete_licence_policy(owner=owner, slug_perm=identifier)

    click.secho("OK", fg="green")
