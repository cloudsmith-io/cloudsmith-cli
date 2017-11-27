"""CLI - Configuration."""
from __future__ import absolute_import, print_function, unicode_literals

from click_configfile import ConfigFileReader, Param, SectionSchema
from click_configfile import matches_section
import click
import six
from . import utils


class ConfigSchema(object):
    """Schema for standard configuration."""

    @matches_section("default")
    class Default(SectionSchema):
        api_host = Param(type=str)
        api_proxy = Param(type=str)
        api_user_agent = Param(type=str)

    @matches_section("profile:*")
    class Profile(Default):
        pass


class ConfigReader(ConfigFileReader):
    """Reader for standard configuration."""
    config_files = [
        "config.ini"
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
        if not section_name or section_name == 'default':
            return 'default'
        else:
            return section_name


class CredentialsSchema(object):
    """Schema for credentials configuration."""

    @matches_section("default")
    class Default(SectionSchema):
        api_key = Param(type=str)

    @matches_section("profile:*")
    class Profile(Default):
        pass


class CredentialsReader(ConfigFileReader):
    """Reader for credentials configuration."""
    config_files = [
        "credentials.ini"
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
        if not section_name or section_name == 'default':
            return 'default'
        else:
            return section_name


class Options(object):
    DEFAULTS = {
        'api_config': None,
        'api_key': None,
        'api_host': None,
        'api_proxy': None,
        'api_user_agent': None,
        'debug': False,
        'output': None,
        'verbose': False
    }

    def __init__(self, *args, **kwargs):
        super(Options, self).__init__(*args, **kwargs)
        opts = self.DEFAULTS.copy()
        opts.update(kwargs)
        for k, v in six.iteritems(opts):
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

        if profile:
            values = config.get('profile:%s' % profile, {})
            self._load_config_from_dict(values)

    def _load_config_from_dict(self, values):
        """Load configuration from a dictionary."""
        for k, v in six.iteritems(values):
            if not v:
                continue
            setattr(self, k, v)

    def __setattr__(self, name, value):
        if name in self.DEFAULTS:
            # Prevent clears if value was set
            try:
                current_value = getattr(self, name)
                if value is None and current_value is not None:
                    return
            except AttributeError:
                pass

        super(Options, self).__setattr__(name, value)

    @property
    def api_user_agent(self):
        return utils.make_user_agent(prefix=self._user_agent)

    @api_user_agent.setter
    def api_user_agent(self, value):
        self._user_agent = value


def get_or_create_options(ctx):
    """Get or create the options object."""
    return ctx.ensure_object(Options)
