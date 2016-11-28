"""CLI - Decorators."""
from __future__ import absolute_import, print_function, unicode_literals
import functools
import os

import click
import six
from ..core.api.init import initialise_api as _initialise_api
from . import config
from . import utils


CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


class Options(dict):
    """Context for storing options/arguments."""
    pass


def common_cli_config_options(f):
    """Add common CLI config options to commands."""
    @click.option(
        '-c', '--config-file', type=click.Path(
            dir_okay=False, exists=True, writable=False, resolve_path=True
        ),
        help="The path to your config.ini file.")
    @click.option(
        '--credentials-file', type=click.Path(
            dir_okay=False, exists=True, writable=False, resolve_path=True
        ),
        help="The path to your credentials.ini file.")
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        opts = kwargs.pop('opts', ctx.ensure_object(Options))
        opts.setdefault('CONFIG_FILE', kwargs.pop('config_file'))
        opts.setdefault('CREDENTIALS_FILE', kwargs.pop('credentials_file'))

        config_cls = config.ConfigReader
        config_file = opts['CONFIG_FILE']
        if config_file:
            config_cls.config_searchpath = [opts['CONFIG_FILE']]
        creds_cls = config.CredentialsReader
        creds_file = opts['CREDENTIALS_FILE']
        if creds_file:
            creds_cls.config_searchpath = [opts['CONFIG_FILE']]

        for config_map in (
                config_cls.read_config(),
                creds_cls.read_config()):
            for k, v in six.iteritems(config_map):
                if not v:
                    continue
                opts[k.upper()] = v

        kwargs['opts'] = opts
        return ctx.invoke(f, *args, **kwargs)
    return wrapper


def common_cli_output_options(f):
    """Add common CLI output options to commands."""
    @click.option(
        '-d', '--debug', default=False, is_flag=True,
        help="Produce debug output during processing.")
    @click.option(
        '-F', '--format', default='normal',
        type=click.Choice(['normal', 'json', 'raw_json']),
        help="Determines how output is formatted.")
    @click.option(
        '-v', '--verbose', is_flag=True, default=False,
        help="Produce more output during processing.")
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        opts = kwargs.pop('opts', ctx.ensure_object(Options))
        opts.setdefault('DEBUG', kwargs.pop('debug'))
        opts.setdefault('FORMAT', kwargs.pop('format'))
        opts.setdefault('VERBOSE', kwargs.pop('verbose'))
        kwargs['opts'] = opts
        return ctx.invoke(f, *args, **kwargs)
    return wrapper


def common_api_auth_options(f):
    """Add common API authentication options to commands."""
    @click.option(
        '-k', '--api-key', hide_input=True, envvar='API_KEY',
        help="The API key for authenticating with the API.")
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        opts = kwargs.pop('opts', ctx.ensure_object(Options))
        opts.setdefault('API_KEY', kwargs.pop('api_key'))
        kwargs['opts'] = opts
        return ctx.invoke(f, *args, **kwargs)
    return wrapper


def initialise_api(f):
    """Initialise the Cloudsmith API for use."""
    @click.option(
        '-H', '--api-host',
        help="The API host to connect to.")
    @click.option(
        '-P', '--api-proxy',
        help="The API proxy to connect through.")
    @click.option(
        '-U', '--api-user-agent',
        help="The user agent to use for requests.")
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        opts = kwargs.pop('opts', ctx.ensure_object(Options))
        opts.setdefault('API_HOST', kwargs.pop('api_host'))
        opts.setdefault('API_PROXY', kwargs.pop('api_proxy'))
        opts.setdefault(
            'API_USER_AGENT',
            utils.make_user_agent(prefix=kwargs.pop('api_user_agent'))
        )

        if 'API_CONFIG' not in opts:
            opts['API_CONFIG'] = _initialise_api(
                debug=opts.get('DEBUG', False),
                host=opts.get('API_HOST'),
                key=opts.get('API_KEY'),
                proxy=opts.get('API_PROXY'),
                user_agent=opts.get('API_USER_AGENT')
            )

        kwargs['opts'] = opts
        return ctx.invoke(f, *args, **kwargs)
    return wrapper
