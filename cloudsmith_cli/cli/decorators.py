# -*- coding: utf-8 -*-
"""CLI - Decorators."""
from __future__ import absolute_import, print_function, unicode_literals

import functools

import click

from ..core.api.init import initialise_api as _initialise_api
from . import config, utils, validators


def common_package_action_options(f):
    """Add common options for package actions."""

    @click.option(
        "-s",
        "--skip-errors",
        default=False,
        is_flag=True,
        help="Skip/ignore errors when copying packages.",
    )
    @click.option(
        "-W",
        "--no-wait-for-sync",
        default=False,
        is_flag=True,
        help="Don't wait for package synchronisation to complete before " "exiting.",
    )
    @click.option(
        "-I",
        "--wait-interval",
        default=5.0,
        type=float,
        show_default=True,
        help="The time in seconds to wait between checking synchronisation.",
    )
    @click.option(
        "--sync-attempts",
        default=3,
        type=int,
        help="Number of times to attempt package synchronisation. If the "
        "package fails the first time, the client will attempt to "
        "automatically resynchronise it.",
    )
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        # pylint: disable=missing-docstring
        return ctx.invoke(f, *args, **kwargs)

    return wrapper


def common_cli_config_options(f):
    """Add common CLI config options to commands."""

    @click.option(
        "-C",
        "--config-file",
        envvar="CLOUDSMITH_CONFIG_FILE",
        type=click.Path(dir_okay=True, exists=True, writable=False, resolve_path=True),
        help="The path to your config.ini file.",
    )
    @click.option(
        "--credentials-file",
        envvar="CLOUDSMITH_CREDENTIALS_FILE",
        type=click.Path(dir_okay=True, exists=True, writable=False, resolve_path=True),
        help="The path to your credentials.ini file.",
    )
    @click.option(
        "-P",
        "--profile",
        default=None,
        envvar="CLOUDSMITH_PROFILE",
        help="The name of the profile to use for configuration.",
    )
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        # pylint: disable=missing-docstring
        opts = config.get_or_create_options(ctx)
        profile = kwargs.pop("profile")
        config_file = kwargs.pop("config_file")
        creds_file = kwargs.pop("credentials_file")
        opts.load_config_file(path=config_file, profile=profile)
        opts.load_creds_file(path=creds_file, profile=profile)
        kwargs["opts"] = opts
        return ctx.invoke(f, *args, **kwargs)

    return wrapper


def common_cli_output_options(f):
    """Add common CLI output options to commands."""

    @click.option(
        "-d",
        "--debug",
        default=False,
        is_flag=True,
        help="Produce debug output during processing.",
    )
    @click.option(
        "-F",
        "--output-format",
        default="pretty",
        type=click.Choice(["pretty", "json", "pretty_json"]),
        help="Determines how output is formatted. This is only supported by a "
        "subset of the commands at the moment (e.g. list).",
    )
    @click.option(
        "-v",
        "--verbose",
        is_flag=True,
        default=False,
        help="Produce more output during processing.",
    )
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        # pylint: disable=missing-docstring
        opts = config.get_or_create_options(ctx)
        opts.debug = kwargs.pop("debug")
        opts.output = kwargs.pop("output_format")
        opts.verbose = kwargs.pop("verbose")
        kwargs["opts"] = opts
        return ctx.invoke(f, *args, **kwargs)

    return wrapper


def common_cli_list_options(f):
    """Add common list options to commands."""

    @click.option(
        "-p",
        "--page",
        default=1,
        type=int,
        help="The page to view for lists, where 1 is the first page",
        callback=validators.validate_page,
    )
    @click.option(
        "-l",
        "--page-size",
        default=30,
        type=int,
        help="The amount of items to view per page for lists.",
        callback=validators.validate_page_size,
    )
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        # pylint: disable=missing-docstring
        opts = config.get_or_create_options(ctx)
        kwargs["opts"] = opts
        return ctx.invoke(f, *args, **kwargs)

    return wrapper


def common_api_auth_options(f):
    """Add common API authentication options to commands."""

    @click.option(
        "-k",
        "--api-key",
        hide_input=True,
        envvar="CLOUDSMITH_API_KEY",
        help="The API key for authenticating with the API.",
    )
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        # pylint: disable=missing-docstring
        opts = config.get_or_create_options(ctx)
        opts.api_key = kwargs.pop("api_key")
        kwargs["opts"] = opts
        return ctx.invoke(f, *args, **kwargs)

    return wrapper


def initialise_api(f):
    """Initialise the Cloudsmith API for use."""

    @click.option(
        "--api-host", envvar="CLOUDSMITH_API_HOST", help="The API host to connect to."
    )
    @click.option(
        "--api-proxy",
        envvar="CLOUDSMITH_API_PROXY",
        help="The API proxy to connect through.",
    )
    @click.option(
        "--api-user-agent",
        envvar="CLOUDSMITH_API_USER_AGENT",
        help="The user agent to use for requests.",
    )
    @click.option(
        "--api-headers",
        envvar="CLOUDSMITH_API_HEADERS",
        help="A CSV list of extra headers (key=value) to send to the API.",
    )
    @click.option(
        "-R",
        "--without-rate-limit",
        default=False,
        is_flag=True,
        help="Don't obey the suggested rate limit interval. The CLI will "
        "automatically sleep between commands to ensure that you do "
        "not hit the server-side rate limit.",
    )
    @click.option(
        "--rate-limit-warning",
        default=30,
        help="When rate limiting, display information that it is happening "
        "if wait interval is higher than this setting. By default no "
        "information will be printed. Set to zero to always see it.",
    )
    @click.option(
        "--error-retry-max",
        default=6,
        help="The maximum amount of times to retry on errors received from "
        "the API, as determined by the --error-retry-codes parameter.",
    )
    @click.option(
        "--error-retry-backoff",
        default=0.23,
        type=float,
        help="The backoff factor determines how long to wait in seconds "
        "between error retries. The backoff factor is multiplied by the "
        "amount of retries so far. So if 0.1, then the wait is 0.1s then "
        "0.2s, then 0.4s, and so forth.",
    )
    @click.option(
        "--error-retry-codes",
        default="500,502,503,504",
        help="The status codes that when received from the API will cause "
        "a retry (if --error-retry-max is > 0). By default this will be for "
        "500, 502, 503 and 504 error codes.",
    )
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        # pylint: disable=missing-docstring
        opts = config.get_or_create_options(ctx)
        opts.api_host = kwargs.pop("api_host")
        opts.api_proxy = kwargs.pop("api_proxy")
        opts.api_user_agent = kwargs.pop("api_user_agent")
        opts.api_headers = kwargs.pop("api_headers")
        opts.rate_limit = not kwargs.pop("without_rate_limit")
        opts.rate_limit_warning = kwargs.pop("rate_limit_warning")
        opts.error_retry_max = kwargs.pop("error_retry_max")
        opts.error_retry_backoff = kwargs.pop("error_retry_backoff")
        opts.error_retry_codes = kwargs.pop("error_retry_codes")

        def call_print_rate_limit_info_with_opts(rate_info, atexit=False):
            utils.print_rate_limit_info(opts, rate_info, atexit=atexit)

        opts.api_config = _initialise_api(
            debug=opts.debug,
            host=opts.api_host,
            key=opts.api_key,
            proxy=opts.api_proxy,
            user_agent=opts.api_user_agent,
            headers=opts.api_headers,
            rate_limit=opts.rate_limit,
            rate_limit_callback=call_print_rate_limit_info_with_opts,
            error_retry_max=opts.error_retry_max,
            error_retry_backoff=opts.error_retry_backoff,
            error_retry_codes=opts.error_retry_codes,
        )

        kwargs["opts"] = opts
        return ctx.invoke(f, *args, **kwargs)

    return wrapper
