# -*- coding: utf-8 -*-
"""CLI/Commands - Get an API token."""
from __future__ import absolute_import, print_function, unicode_literals

import collections
import stat

import click

from ...core.api.user import get_user_token
from ...core.utils import get_help_website
from .. import decorators
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from .main import main

ConfigValues = collections.namedtuple(
    "ConfigValues", ["reader", "present", "mode", "data"]
)


def validate_login(ctx, param, value):
    """Ensure that login is not blank."""
    # pylint: disable=unused-argument
    value = value.strip()
    if not value:
        raise click.BadParameter("The value cannot be blank.", param=param)
    return value


def create_config_files(ctx, opts, api_key):
    """Create default config files."""
    # pylint: disable=unused-argument
    config_reader = opts.get_config_reader()
    creds_reader = opts.get_creds_reader()
    has_config = config_reader.has_default_file()
    has_creds = creds_reader.has_default_file()

    if has_config and has_creds:
        create = False
    else:
        click.echo()
        create = click.confirm(
            "No default config file(s) found, do you want to create them?"
        )

    click.echo()
    if not create:
        click.secho(
            "For reference here are your default config file locations:", fg="yellow"
        )
    else:
        click.secho(
            "Great! Let me just create your default configs for you now ...", fg="green"
        )

    configs = (
        ConfigValues(reader=config_reader, present=has_config, mode=None, data={}),
        ConfigValues(
            reader=creds_reader,
            present=has_creds,
            mode=stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP,
            data={"api_key": api_key},
        ),
    )

    has_errors = False
    for config in configs:
        click.echo(
            "%(name)s config file: %(filepath)s ... "
            % {
                "name": click.style(config.reader.config_name.capitalize(), bold=True),
                "filepath": click.style(
                    config.reader.get_default_filepath(), fg="magenta"
                ),
            },
            nl=False,
        )

        if not config.present and create:
            try:
                ok = config.reader.create_default_file(
                    data=config.data, mode=config.mode
                )
            except (OSError, IOError) as exc:
                ok = False
                error_message = exc.strerror
                has_errors = True

            if ok:
                click.secho("CREATED", fg="green")
            else:
                click.secho("ERROR", fg="red")
                click.secho(
                    "The following error occurred while trying to "
                    "create the file: %(message)s"
                    % {"message": click.style(error_message, fg="red")}
                )
            continue

        click.secho("EXISTS" if config.present else "NOT CREATED", fg="yellow")

    return create, has_errors


@main.command(aliases=["token"])
@click.option(
    "-l",
    "--login",
    required=True,
    callback=validate_login,
    prompt=True,
    help="Your Cloudsmith login account (email address).",
)
@click.password_option("-p", "--password", help="Your Cloudsmith login password.")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.initialise_api
@click.pass_context
def login(ctx, opts, login, password):  # pylint: disable=redefined-outer-name
    """Retrieve your API authentication token/key via login."""
    click.echo(
        "Retrieving API token for %(login)s ... "
        % {"login": click.style(login, bold=True)},
        nl=False,
    )

    context_msg = "Failed to retrieve the API token!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            api_key = get_user_token(login=login, password=password)

    click.secho("OK", fg="green")

    click.echo(
        "Your API key/token is: %(token)s"
        % {"token": click.style(api_key, fg="magenta")}
    )

    create, has_errors = create_config_files(ctx, opts, api_key=api_key)

    if has_errors:
        click.echo()
        click.secho("Oops, please fix the errors and try again!", fg="red")
        return

    if opts.api_key != api_key:
        click.echo()
        if opts.api_key:
            click.secho(
                "Note: The above API key doesn't match what you have in "
                "your default credentials config file.",
                fg="yellow",
            )
        elif not create:
            click.secho(
                "Note: Don't forget to put your API key in a config file, "
                "export it on the environment, or set it via -k.",
                fg="yellow",
            )
            click.secho(
                "If you need more help please see the documentation: "
                "%(website)s" % {"website": click.style(get_help_website(), bold=True)}
            )
        click.echo()

    click.secho("You're ready to rock, let's start automating!", fg="green")
