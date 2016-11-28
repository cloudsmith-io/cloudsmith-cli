"""CLI - Configuration."""
from __future__ import absolute_import, print_function, unicode_literals

from click_configfile import ConfigFileReader, Param, SectionSchema
from click_configfile import matches_section
import click


class ConfigSchema(object):
    """Schema for standard configuration."""

    @matches_section("default")
    class Default(SectionSchema):
        pass

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
        # Config always gets merged
        return ''


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
