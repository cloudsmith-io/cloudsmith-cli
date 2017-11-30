"""CLI - Configuration."""
from __future__ import absolute_import, print_function, unicode_literals

import click
import six
from click_configfile import (
    ConfigFileReader, Param, SectionSchema, matches_section
)

from . import utils


class ConfigSchema(object):
    """Schema for standard configuration."""

    @matches_section('default')
    class Default(SectionSchema):
        """Default configuration schema."""

        api_host = Param(type=str)
        api_proxy = Param(type=str)
        api_user_agent = Param(type=str)

    @matches_section('profile:*')
    class Profile(Default):
        """Profile-specifi configuration schema."""


class ConfigReader(ConfigFileReader):
    """Reader for standard configuration."""

    config_files = [
        'config.ini'
    ]
    config_section_schemas = [
        ConfigSchema.Default,
        ConfigSchema.Profile
    ]
    config_searchpath = [
        click.get_app_dir('cloudsmith')
    ]

    @classmethod
    def get_storage_name_for(cls, section_name):
        """Get storage name for a configuration section."""
        if not section_name or section_name == 'default':
            return 'default'
        else:
            return section_name


class CredentialsSchema(object):
    """Schema for credentials configuration."""

    @matches_section('default')
    class Default(SectionSchema):
        """Default configuration schema."""

        api_key = Param(type=str)

    @matches_section('profile:*')
    class Profile(Default):
        """Profile-specifi configuration schema."""


class CredentialsReader(ConfigFileReader):
    """Reader for credentials configuration."""

    config_files = [
        'credentials.ini'
    ]
    config_section_schemas = [
        CredentialsSchema.Default,
        CredentialsSchema.Profile
    ]
    config_searchpath = [
        click.get_app_dir('cloudsmith')
    ]

    @classmethod
    def get_storage_name_for(cls, section_name):
        """Get storage name for a configuration section."""
        if not section_name or section_name == 'default':
            return 'default'
        else:
            return section_name


class Options(object):
    """Options object that holds config for the application."""

    def __init__(self, *args, **kwargs):
        """Initialise a new Options object."""
        super(Options, self).__init__(*args, **kwargs)
        self.opts = {}
        for k, v in six.iteritems(kwargs):
            setattr(self, k, v)

    def load_config_file(self, path, profile=None):
        """Load the standard config file."""
        self._load_config(ConfigReader, path, profile=profile)

    def load_creds_file(self, path, profile=None):
        """Load the credentials config file."""
        self._load_config(CredentialsReader, path, profile=profile)

    def _load_config(self, config_cls, path=None, profile=None):
        """Load a configuration file."""
        if path:
            config_cls.searchpath = [path]

        config = config_cls.read_config()

        values = config.get('default', {})
        self._load_config_from_dict(values)

        if profile and profile != 'default':
            values = config.get('profile:%s' % profile, {})
            self._load_config_from_dict(values)

    def _load_config_from_dict(self, values):
        """Load configuration from a dictionary."""
        for k, v in six.iteritems(values):
            if v is None:
                continue
            setattr(self, k, v)

    @property
    def api_config(self):
        """Get value for API config dictionary."""
        return self._get_option('api_config')

    @api_config.setter
    def api_config(self, value):
        """Set value for API config dictionary."""
        self._set_option('api_config', value)

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
