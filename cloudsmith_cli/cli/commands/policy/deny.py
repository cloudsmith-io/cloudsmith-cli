"""Commands for deny policies."""
import click

from ... import command, decorators, utils
from ...exceptions import handle_api_exceptions
from ...utils import maybe_spinner, fmt_datetime
from ....core.api import orgs
from .command import policy


def print_deny_policies(policies):
    """Print deny policies as a table."""
    headers = [
        "Name", "Description", "Package Query", "Enabled",
        "Created", "Updated", "Identifier"
    ]

    rows = [
        [
            click.style(policy["name"], fg="cyan"),
            click.style(policy["description"], fg="yellow"),
            click.style(policy.get("package_query_string", ""), fg="yellow"),
            click.style(
                "Yes" if policy.get("enabled") else "No",
                fg="green" if policy.get("enabled") else "red"
            ),
            click.style(fmt_datetime(policy["created_at"]), fg="blue"),
            click.style(fmt_datetime(policy["updated_at"]), fg="blue"),
            click.style(policy["slug_perm"], fg="green"),
        ]
        for policy in policies
    ]

    click.echo()
    utils.pretty_print_table(headers, rows)
    click.echo()


@policy.group(cls=command.AliasGroup, name="deny", aliases=[])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def deny_policy(*args, **kwargs):
    """Manage deny policies for an organization."""
    pass


@deny_policy.command(name="list", aliases=["ls"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument("owner")
@click.pass_context
def list_deny_policies(ctx, opts, owner):
    """List deny policies for an organization."""
    use_stderr = opts.output != "pretty"
    click.echo("Getting deny policies ... ", nl=False, err=use_stderr)

    context_msg = "Failed to get deny policies!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            data, _ = orgs.list_deny_policies(
                owner=owner, page=1, page_size=100
            )

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, data):
        return

    print_deny_policies(data)


@deny_policy.command(name="create", aliases=["new"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument("owner")
@click.argument("policy_config_file", type=click.File("rb"))
@click.pass_context
def create_deny_policy(ctx, opts, owner, policy_config_file):
    """Create a deny policy for an organization."""
    import json

    use_stderr = opts.output != "pretty"
    policy_config = json.load(policy_config_file)

    policy_name = policy_config.get("name")
    if not policy_name:
        raise click.BadParameter(
            "Name is required for creating a deny policy.", param="name"
        )

    click.secho(
        "Creating %(name)s deny policy for the %(owner)s namespace ..."
        % {
            "name": click.style(policy_name, bold=True),
            "owner": click.style(owner, bold=True)
        },
        nl=False, err=use_stderr
    )

    context_msg = "Failed to create the deny policy!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            data = orgs.create_deny_policy(
                owner=owner, policy_config=policy_config
            )

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, [data]):
        return

    print_deny_policies([data])


@deny_policy.command(name="get")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument("owner")
@click.argument("identifier")
@click.pass_context
def get_deny_policy(ctx, opts, owner, identifier):
    """Get a deny policy for an organization."""
    use_stderr = opts.output != "pretty"
    click.echo("Getting deny policy ... ", nl=False, err=use_stderr)

    context_msg = "Failed to get deny policy!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            data = orgs.get_deny_policy(owner=owner, slug_perm=identifier)

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, [data]):
        return

    print_deny_policies([data])


@deny_policy.command(name="update", aliases=["set"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument("owner")
@click.argument("identifier")
@click.argument("policy_config_file", type=click.File("rb"))
@click.pass_context
def update_deny_policy(ctx, opts, owner, identifier, policy_config_file):
    """Update a deny policy for an organization."""
    import json

    use_stderr = opts.output != "pretty"
    policy_config = json.load(policy_config_file)

    click.secho(
        "Updating %(identifier)s deny policy in the %(owner)s namespace ..."
        % {
            "identifier": click.style(identifier, bold=True),
            "owner": click.style(owner, bold=True)
        },
        nl=False, err=use_stderr
    )

    context_msg = "Failed to update the deny policy!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            data = orgs.update_deny_policy(
                owner=owner, slug_perm=identifier, policy_config=policy_config
            )

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, [data]):
        return

    print_deny_policies([data])


@deny_policy.command(name="delete", aliases=["rm"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument("owner")
@click.argument("identifier")
@click.option(
    "-y", "--yes", default=False, is_flag=True,
    help="Assume yes as default answer to questions (this is dangerous!)"
)
@click.pass_context
def delete_deny_policy(ctx, opts, owner, identifier, yes):
    """Delete a deny policy for an organization."""
    delete_args = {
        "namespace": click.style(owner, bold=True),
        "identifier": click.style(identifier, bold=True),
    }

    prompt = (
        "delete the %(identifier)s deny policy from the %(namespace)s namespace"
        % delete_args
    )

    if not utils.confirm_operation(prompt, assume_yes=yes):
        return

    click.secho(
        "Deleting %(identifier)s from the %(namespace)s namespace ... "
        % delete_args,
        nl=False
    )

    context_msg = "Failed to delete the deny policy!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            orgs.delete_deny_policy(owner=owner, slug_perm=identifier)

    click.secho("OK", fg="green")
