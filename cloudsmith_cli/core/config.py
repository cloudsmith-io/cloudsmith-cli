import collections
import stat

import click

from .utils import get_help_website

ConfigValues = collections.namedtuple(
    "ConfigValues", ["reader", "present", "mode", "data"]
)


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
            except OSError as exc:
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


def new_config_messaging(has_errors, opts, create, api_key):
    """Provide messaging to user after generating new configs"""
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
