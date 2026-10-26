# Copyright 2026 Cloudsmith Ltd
"""Which settings were set in config.ini / credentials.ini, by section.

``ConfigReader.read_config()`` fills schema defaults, so it cannot tell an
explicit key from a default; this reads the raw files and reports key
presence only. Values are never read.
"""

import configparser
import os

from ..core.usage.event import SETTING_ALIASES
from . import config


def _files(reader, explicit):
    paths = [explicit] if explicit else []
    paths.extend(
        name if os.path.isabs(name) else os.path.join(searchpath, name)
        for searchpath in reader.config_searchpath
        for name in reader.config_files
    )
    return [p for p in paths if p and os.path.isfile(p)]


def _declared(schema):
    """Key names the CLI reads for a section schema (never user-authored keys)."""
    return {
        param.name
        for param in vars(schema).values()
        if isinstance(param, config.ConfigParam)
    }


def _keys(paths, section, declared):
    keys = set()
    for path in paths:
        parser = configparser.RawConfigParser()
        try:
            parser.read(path, encoding="utf-8")
        except (configparser.Error, UnicodeDecodeError, OSError):
            continue
        if parser.has_section(section):
            keys.update(parser.options(section))
    return keys & declared


def detect(
    *, config_file: str | None, creds_file: str | None, profile: str | None
) -> dict[str, str]:
    """Map each setting present in the ini files to where it was set."""
    found: dict[str, str] = {}
    for reader, schema, explicit, base in (
        (config.ConfigReader, config.ConfigSchema.Default, config_file, "config"),
        (
            config.CredentialsReader,
            config.CredentialsSchema.Default,
            creds_file,
            "credentials",
        ),
    ):
        paths = _files(reader, explicit)
        declared = _declared(schema)
        for key in _keys(paths, "default", declared):
            found[SETTING_ALIASES.get(key, key)] = f"{base}_file"
        if profile and profile != "default":
            for key in _keys(paths, f"profile:{profile}", declared):
                found[SETTING_ALIASES.get(key, key)] = f"{base}_profile"
    return found
