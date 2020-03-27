# -*- coding: utf-8 -*-
"""CLI - Configuration."""
from __future__ import absolute_import, print_function, unicode_literals

import os
import re
import threading

import click
import six
from click_configfile import ConfigFileReader, Param, SectionSchema, matches_section

from ..core.utils import get_data_path, read_file
from . import utils, validators

OPTIONS = threading.local()


class ConfigParam(Param):
    # For compatibility with click>=7.0
    def __init__(self, *args, **kwargs):
        super(ConfigParam, self).__init__(*args, **kwargs)
        self.ctx = None

    def parse(self, text):
        if text:
            text = text.strip()
        if self.type.name == "boolean":
            if not text:
                return None
        return super(ConfigParam, self).parse(text)

    def get_error_hint(self, ctx):
        if self.ctx:
            files = []
            for path in self.ctx.config_searchpath:
                for filename in self.ctx.config_files:
                    files.append(os.path.join(path, filename))
            files = " or ".join(files)
            msg = "%s in %s" % (self.name, files)
        else:
            msg = "%s in a config file" % (self.name,)
        return msg


def get_default_config_path():
    """Get the default path to cloudsmith config files."""
    return click.get_app_dir("cloudsmith")


class ConfigSchema(object):
    """Schema for standard configuration."""

    @matches_section("default")
    class Default(SectionSchema):
        """Default configuration schema."""

        api_headers = ConfigParam(name="api_headers", type=str)
        api_host = ConfigParam(name="api_host", type=str)
        api_proxy = ConfigParam(name="api_ssl_verify", type=str)
        api_ssl_verify = ConfigParam(name="api_ssl_verify", type=bool, default=True)
        api_user_agent = ConfigParam(name="api_user_agent", type=str)

    @matches_section("profile:*")
    class Profile(Default):
        """Profile-specific configuration schema."""


class ConfigReader(ConfigFileReader):
    """Reader for standard configuration."""

    config_files = ["config.ini"]
    config_name = "standard"
    config_searchpath = [get_default_config_path()]
    config_section_schemas = [ConfigSchema.Default, ConfigSchema.Profile]

    @classmethod
    def select_config_schema_for(cls, section_name):
        section_schema = super(ConfigReader, cls).select_config_schema_for(section_name)
        for v in six.itervalues(section_schema.__dict__):
            if isinstance(v, ConfigParam):
                v.ctx = cls
        return section_schema

    @classmethod
    def get_storage_name_for(cls, section_name):
        """Get storage name for a configuration section."""
        if not section_name or section_name == "default":
            return "default"
        return section_name

    @classmethod
    def get_default_filepath(cls):
        """Get the default filepath for the configuratin file."""
        if not cls.config_files:
            return None
        if not cls.config_searchpath:
            return None
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
            v = v or ""
            config = re.sub(
                r"^(%(key)s)\s*=\s*$" % {"key": k},
                "%(key)s = %(value)s" % {"key": k, "value": v},
                config,
                flags=re.MULTILINE,
            )

        dirpath = os.path.dirname(filepath)
        if not os.path.exists(dirpath):
            os.makedirs(dirpath)
        with click.open_file(filepath, "w+") as f:
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
        if path and os.path.exists(path):
            if os.path.isdir(path):
                cls.config_searchpath.insert(0, path)
            else:
                cls.config_files.insert(0, path)

        config = cls.read_config()
        values = config.get("default", {})
        cls._load_values_into_opts(opts, values)

        if profile and profile != "default":
            values = config.get("profile:%s" % profile, {})
            cls._load_values_into_opts(opts, values)

        return values

    @staticmethod
    def _load_values_into_opts(opts, values):
        for k, v in six.iteritems(values):
            if v is None:
                continue
            if isinstance(v, six.string_types):
                if v.startswith('"') or v.startswith("'"):
                    v = v[1:]
                if v.endswith('"') or v.endswith("'"):
                    v = v[:-1]
                if not v:
                    continue
            else:
                if v is None:
                    continue
            setattr(opts, k, v)


class CredentialsSchema(object):
    """Schema for credentials configuration."""

    @matches_section("default")
    class Default(SectionSchema):
        """Default configuration schema."""

        api_key = ConfigParam(name="api_key", type=str)

    @matches_section("profile:*")
    class Profile(Default):
        """Profile-specific configuration schema."""


class CredentialsReader(ConfigReader):
    """Reader for credentials configuration."""

    config_files = ["credentials.ini"]
    config_name = "credentials"
    config_searchpath = [get_default_config_path()]
    config_section_schemas = [CredentialsSchema.Default, CredentialsSchema.Profile]


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
        return self._get_option("api_config")

    @api_config.setter
    def api_config(self, value):
        """Set value for API config dictionary."""
        self._set_option("api_config", value)

    @property
    def api_headers(self):
        """Get value for API headers."""
        return self._get_option("api_headers")

    @api_headers.setter
    def api_headers(self, value):
        """Set value for API headers."""
        value = validators.validate_api_headers("api_headers", value)
        self._set_option("api_headers", value)

    @property
    def api_host(self):
        """Get value for API host."""
        return self._get_option("api_host")

    @api_host.setter
    def api_host(self, value):
        """Set value for API host."""
        self._set_option("api_host", value)

    @property
    def api_key(self):
        """Get value for API key."""
        return self._get_option("api_key")

    @api_key.setter
    def api_key(self, value):
        """Set value for API key."""
        self._set_option("api_key", value)

    @property
    def api_proxy(self):
        """Get value for API proxy."""
        return self._get_option("api_proxy")

    @api_proxy.setter
    def api_proxy(self, value):
        """Set value for API proxy."""
        self._set_option("api_proxy", value)

    @property
    def api_ssl_verify(self):
        """Get value for API SSL verify."""
        return self._get_option("api_ssl_verify", default=True)

    @api_ssl_verify.setter
    def api_ssl_verify(self, value):
        """Set value for API SSL verify."""
        self._set_option("api_ssl_verify", value, allow_clear=False)

    @property
    def api_user_agent(self):
        """Get value for API user agent."""
        return utils.make_user_agent(prefix=self._get_option("api_user_agent"))

    @api_user_agent.setter
    def api_user_agent(self, value):
        """Set value for API user agent."""
        self._set_option("api_user_agent", value)

    @property
    def rate_limit(self):
        """Get value for rate limiting."""
        return self._get_option("rate_limit", default=True)

    @rate_limit.setter
    def rate_limit(self, value):
        """Set value for rate limiting."""
        self._set_option("rate_limit", value)

    @property
    def rate_limit_warning(self):
        """Get value for rate limiting warning (in seconds)."""
        return self._get_option("rate_limit_warning", default=30)

    @rate_limit_warning.setter
    def rate_limit_warning(self, value):
        """Set value for rate limiting warning (in seconds)."""
        self._set_option("rate_limit_warning", value)

    @property
    def always_show_rate_limit(self):
        """Get value for rate limiting warning (in seconds)."""
        return self._get_option("always_show_rate_limit", default=False)

    @always_show_rate_limit.setter
    def always_show_rate_limit(self, value):
        """Set value for rate limiting warning (in seconds)."""
        self._set_option("always_show_rate_limit", value)

    @property
    def debug(self):
        """Get value for debug flag."""
        return self._get_option("debug", default=False)

    @debug.setter
    def debug(self, value):
        """Set value for debug flag."""
        self._set_option("debug", bool(value))

    @property
    def output(self):
        """Get value for output format."""
        return self._get_option("output")

    @output.setter
    def output(self, value):
        """Set value for output format."""
        self._set_option("output", value)

    @property
    def verbose(self):
        """Get value for verbose flag."""
        return self._get_option("verbose", default=False)

    @verbose.setter
    def verbose(self, value):
        """Set value for verbose flag."""
        self._set_option("verbose", bool(value))

    @property
    def error_retry_max(self):
        """Get value for error_retry_max."""
        return self._get_option("error_retry_max", default=5)

    @error_retry_max.setter
    def error_retry_max(self, value):
        """Set value for error_retry_max."""
        self._set_option("error_retry_max", int(value))

    @property
    def error_retry_backoff(self):
        """Get value for error_retry_backoff."""
        return self._get_option("error_retry_backoff", default=0.23)

    @error_retry_backoff.setter
    def error_retry_backoff(self, value):
        """Set value for error_retry_backoff."""
        self._set_option("error_retry_backoff", float(value))

    @property
    def error_retry_codes(self):
        """Get value for error_retry_codes."""
        return self._get_option("error_retry_codes", default=[500, 502, 503, 504])

    @error_retry_codes.setter
    def error_retry_codes(self, value):
        """Set value for error_retry_codes."""
        if isinstance(value, six.string_types):
            value = [int(x) for x in value.split(",")]
        self._set_option("error_retry_codes", value)

    def _get_option(self, name, default=None):
        """Get value for an option."""
        value = self.opts.get(name)
        if value is None:
            return default
        return value

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
    try:
        return OPTIONS.value
    except AttributeError:
        OPTIONS.value = ctx.ensure_object(Options)
        return OPTIONS.value
