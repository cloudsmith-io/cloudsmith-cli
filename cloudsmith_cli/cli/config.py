"""CLI - Configuration."""
from __future__ import absolute_import, print_function, unicode_literals

import os
import re

import click
import six
from click_configfile import (
    ConfigFileReader, Param, SectionSchema, matches_section
)

from . import utils, validators
from ..core.utils import get_data_path, read_file


def get_default_config_path():
    """Get the default path to cloudsmith config files."""
    return click.get_app_dir('cloudsmith')


class ConfigSchema(object):
    """Schema for standard configuration."""

    @matches_section('default')
    class Default(SectionSchema):
        """Default configuration schema."""

        api_headers = Param(type=str)
        api_host = Param(type=str)
        api_proxy = Param(type=str)
        api_user_agent = Param(type=str)

    @matches_section('profile:*')
    class Profile(Default):
        """Profile-specific configuration schema."""


class ConfigReader(ConfigFileReader):
    """Reader for standard configuration."""

    config_files = [
        'config.ini'
    ]
    config_name = 'standard'
    config_searchpath = [
        get_default_config_path()
    ]
    config_section_schemas = [
        ConfigSchema.Default,
        ConfigSchema.Profile
    ]

    @classmethod
    def get_storage_name_for(cls, section_name):
        """Get storage name for a configuration section."""
        if not section_name or section_name == 'default':
            return 'default'
        else:
            return section_name

    @classmethod
    def get_default_filepath(cls):
        """Get the default filepath for the configuratin file."""
        if not cls.config_files:
            return
        if not cls.config_searchpath:
            return
        filename = cls.config_files[0]
        filepath = cls.config_searchpath[0]
        return os.path.join(filepath, filename)

    @classmethod
    def create_default_file(cls, data=None, mode=None):
        """Create a config file and override data if specified."""
        filepath = cls.get_default_filepath()
        if not filepath:
            return False

        filename = os.path.basename(filepath)
        config = read_file(get_data_path(), filename)

        # Find and replace data in default config
        data = data or {}
        for k, v in six.iteritems(data):
            v = v or ''
            config = re.sub(
                r'^(%(key)s) =[ ]*$' % {'key': k},
                '%(key)s = %(value)s' % {'key': k, 'value': v},
                config, flags=re.MULTILINE
            )

        dirpath = os.path.dirname(filepath)
        if not os.path.exists(dirpath):
            os.makedirs(dirpath)
        with click.open_file(filepath, 'w+') as f:
            f.write(config)

        if mode is not None:
            os.chmod(filepath, mode)

        return True

    @classmethod
    def has_default_file(cls):
        """Check if a configuration file exists."""
        for filename in cls.config_files:
            for searchpath in cls.config_searchpath:
                path = os.path.join(searchpath, filename)
                if os.path.exists(path):
                    return True

        return False

    @classmethod
    def load_config(cls, opts, path=None, profile=None):
        """Load a configuration file into an options object."""
        if path:
            cls.searchpath = [path]

        config = cls.read_config()
        values = config.get('default', {})
        cls._load_values_into_opts(opts, values)

        if profile and profile != 'default':
            values = config.get('profile:%s' % profile, {})
            cls._load_values_into_opts(opts, values)

        return values

    @staticmethod
    def _load_values_into_opts(opts, values):
        for k, v in six.iteritems(values):
            if v is None:
                continue
            if v.startswith('"') or v.startswith('\''):
                v = v[1:]
            if v.endswith('"') or v.endswith('\''):
                v = v[:-1]
            if not v:
                continue
            setattr(opts, k, v)


class CredentialsSchema(object):
    """Schema for credentials configuration."""

    @matches_section('default')
    class Default(SectionSchema):
        """Default configuration schema."""

        api_key = Param(type=str)

    @matches_section('profile:*')
    class Profile(Default):
        """Profile-specific configuration schema."""


class CredentialsReader(ConfigReader):
    """Reader for credentials configuration."""

    config_files = [
        'credentials.ini'
    ]
    config_name = 'credentials'
    config_searchpath = [
        get_default_config_path()
    ]
    config_section_schemas = [
        CredentialsSchema.Default,
        CredentialsSchema.Profile
    ]


class Options(object):
    """Options object that holds config for the application."""

    def __init__(self, *args, **kwargs):
        """Initialise a new Options object."""
        super(Options, self).__init__(*args, **kwargs)
        self.opts = {}
        for k, v in six.iteritems(kwargs):
            setattr(self, k, v)

    @staticmethod
    def get_config_reader():
        """Get the non-credentials config reader class."""
        return ConfigReader

    @staticmethod
    def get_creds_reader():
        """Get the credentials config reader class."""
        return CredentialsReader

    def load_config_file(self, path, profile=None):
        """Load the standard config file."""
        config_cls = self.get_config_reader()
        return config_cls.load_config(self, path, profile=profile)

    def load_creds_file(self, path, profile=None):
        """Load the credentials config file."""
        config_cls = self.get_creds_reader()
        return config_cls.load_config(self, path, profile=profile)

    @property
    def api_config(self):
        """Get value for API config dictionary."""
        return self._get_option('api_config')

    @api_config.setter
    def api_config(self, value):
        """Set value for API config dictionary."""
        self._set_option('api_config', value)

    @property
    def api_headers(self):
        """Get value for API headers."""
        return self._get_option('api_headers')

    @api_headers.setter
    def api_headers(self, value):
        """Set value for API headers."""
        value = validators.validate_api_headers('api_headers', value)
        self._set_option('api_headers', value)

    @property
    def api_host(self):
        """Get value for API host."""
        return self._get_option('api_host')

    @api_host.setter
    def api_host(self, value):
        """Set value for API host."""
        self._set_option('api_host', value)

    @property
    def api_key(self):
        """Get value for API key."""
        return self._get_option('api_key')

    @api_key.setter
    def api_key(self, value):
        """Set value for API key."""
        self._set_option('api_key', value)

    @property
    def api_proxy(self):
        """Get value for API proxy."""
        return self._get_option('api_proxy')

    @api_proxy.setter
    def api_proxy(self, value):
        """Set value for API proxy."""
        self._set_option('api_proxy', value)

    @property
    def api_user_agent(self):
        """Get value for API user agent."""
        return utils.make_user_agent(prefix=self._get_option('api_user_agent'))

    @api_user_agent.setter
    def api_user_agent(self, value):
        """Set value for API user agent."""
        self._set_option('api_user_agent', value)

    @property
    def debug(self):
        """Get value for debug flag."""
        return self._get_option('debug', default=False)

    @debug.setter
    def debug(self, value):
        """Set value for debug flag."""
        self._set_option('debug', bool(value))

    @property
    def output(self):
        """Get value for output format."""
        return self._get_option('output')

    @output.setter
    def output(self, value):
        """Set value for output format."""
        self._set_option('output', value)

    @property
    def verbose(self):
        """Get value for verbose flag."""
        return self._get_option('verbose', default=False)

    @verbose.setter
    def verbose(self, value):
        """Set value for verbose flag."""
        self._set_option('verbose', bool(value))

    def _get_option(self, name, default=None):
        """Get value for an option."""
        return self.opts.get(name, default)

    def _set_option(self, name, value, allow_clear=False):
        """Set value for an option."""
        if not allow_clear:
            # Prevent clears if value was set
            try:
                current_value = self._get_option(name)
                if value is None and current_value is not None:
                    return
            except AttributeError:
                pass

        self.opts[name] = value


def get_or_create_options(ctx):
    """Get or create the options object."""
    return ctx.ensure_object(Options)
