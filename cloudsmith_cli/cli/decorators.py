"""CLI - Decorators."""
from __future__ import absolute_import, print_function, unicode_literals

import functools

import click

from . import config
from ..core.api.init import initialise_api as _initialise_api


def common_cli_config_options(f):
    """Add common CLI config options to commands."""
    @click.option(
        '-C', '--config-file', envvar='CLOUDSMITH_CONFIG_FILE',
        type=click.Path(
            dir_okay=False, exists=True, writable=False, resolve_path=True
        ),
        help='The path to your config.ini file.')
    @click.option(
        '--credentials-file', envvar='CLOUDSMITH_CREDENTIALS_FILE',
        type=click.Path(
            dir_okay=False, exists=True, writable=False, resolve_path=True
        ),
        help='The path to your credentials.ini file.')
    @click.option(
        '-P', '--profile', default=None, envvar='CLOUDSMITH_PROFILE',
        help='The name of the profile to use for configuration.')
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        # pylint: disable=missing-docstring
        opts = config.get_or_create_options(ctx)
        profile = kwargs.pop('profile')
        config_file = kwargs.pop('config_file')
        creds_file = kwargs.pop('credentials_file')
        opts.load_config_file(path=config_file, profile=profile)
        opts.load_creds_file(path=creds_file, profile=profile)
        kwargs['opts'] = opts
        return ctx.invoke(f, *args, **kwargs)
    return wrapper


def common_cli_output_options(f):
    """Add common CLI output options to commands."""
    @click.option(
        '-d', '--debug', default=False, is_flag=True,
        help='Produce debug output during processing.')
    @click.option(
        '-F', '--output-format', default='normal',
        type=click.Choice(['normal', 'json', 'raw_json']),
        help='Determines how output is formatted.')
    @click.option(
        '-v', '--verbose', is_flag=True, default=False,
        help='Produce more output during processing.')
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        # pylint: disable=missing-docstring
        opts = config.get_or_create_options(ctx)
        opts.debug = kwargs.pop('debug')
        opts.output = kwargs.pop('output_format')
        opts.verbose = kwargs.pop('verbose')
        kwargs['opts'] = opts
        return ctx.invoke(f, *args, **kwargs)
    return wrapper


def common_api_auth_options(f):
    """Add common API authentication options to commands."""
    @click.option(
        '-k', '--api-key', hide_input=True, envvar='CLOUDSMITH_API_KEY',
        help='The API key for authenticating with the API.')
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        # pylint: disable=missing-docstring
        opts = config.get_or_create_options(ctx)
        opts.api_key = kwargs.pop('api_key')
        kwargs['opts'] = opts
        return ctx.invoke(f, *args, **kwargs)
    return wrapper


def initialise_api(f):
    """Initialise the Cloudsmith API for use."""
    @click.option(
        '--api-host', envvar='CLOUDSMITH_API_HOST',
        help='The API host to connect to.')
    @click.option(
        '--api-proxy', envvar='CLOUDSMITH_API_PROXY',
        help='The API proxy to connect through.')
    @click.option(
        '--api-user-agent', envvar='CLOUDSMITH_API_USER_AGENT',
        help='The user agent to use for requests.')
    @click.option(
        '--api-headers', envvar='CLOUDSMITH_API_HEADERS',
        help='A CSV list of extra headers (key=value) to send to the API.')
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        # pylint: disable=missing-docstring
        opts = config.get_or_create_options(ctx)
        opts.api_host = kwargs.pop('api_host')
        opts.api_proxy = kwargs.pop('api_proxy')
        opts.api_user_agent = kwargs.pop('api_user_agent')
        opts.api_headers = kwargs.pop('api_headers')
        opts.api_config = _initialise_api(
            debug=opts.debug,
            host=opts.api_host,
            key=opts.api_key,
            proxy=opts.api_proxy,
            user_agent=opts.api_user_agent,
            headers=opts.api_headers
        )

        kwargs['opts'] = opts
        return ctx.invoke(f, *args, **kwargs)
    return wrapper
