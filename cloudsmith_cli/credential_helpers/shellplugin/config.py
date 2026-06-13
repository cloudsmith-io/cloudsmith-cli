# Copyright 2026 Cloudsmith Ltd
"""Persistent state for shell-plugin credential helpers.

Records which package-manager formats are enabled and the org/repo + resolved
hosts each is bound to, as ``[package-manager:<format>]`` sections in
``package-managers.ini`` inside the CLI config directory (alongside
``config.ini`` / ``credentials.ini``).
"""

from __future__ import annotations

import configparser
from dataclasses import asdict, dataclass
from pathlib import Path

from ...cli.config import get_default_config_path

DEFAULT_CDN_HOST = "dl.cloudsmith.io"
DEFAULT_UPLOAD_HOST = "maven.cloudsmith.io"
DEFAULT_REGISTRY_ID = "cloudsmith"
DEFAULT_API_HOST = "https://api.cloudsmith.io"

_SECTION_PREFIX = "package-manager:"


@dataclass(frozen=True)
class PluginEntry:
    """A single enabled shell-plugin's binding (org/repo + resolved hosts)."""

    owner: str
    repo: str
    api_host: str = DEFAULT_API_HOST
    cdn_host: str = DEFAULT_CDN_HOST
    upload_host: str = DEFAULT_UPLOAD_HOST
    registry_id: str = DEFAULT_REGISTRY_ID

    @classmethod
    def from_dict(cls, data) -> PluginEntry:
        """Build an entry from a config section, filling defaults."""
        return cls(
            owner=data.get("owner", ""),
            repo=data.get("repo", ""),
            api_host=data.get("api_host") or DEFAULT_API_HOST,
            cdn_host=data.get("cdn_host") or DEFAULT_CDN_HOST,
            upload_host=data.get("upload_host") or DEFAULT_UPLOAD_HOST,
            registry_id=data.get("registry_id") or DEFAULT_REGISTRY_ID,
        )

    def to_dict(self) -> dict:
        """Return the entry as a flat string mapping for the INI section."""
        return asdict(self)


def config_path() -> Path:
    """Return the path to ``package-managers.ini`` in the CLI config dir."""
    return Path(get_default_config_path()) / "package-managers.ini"


def shims_dir() -> Path:
    """Return the directory that holds package-manager shims on PATH."""
    return Path(get_default_config_path()) / "shims"


def _read() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    path = config_path()
    if path.exists():
        parser.read(path, encoding="utf-8")
    return parser


def _write(parser: configparser.ConfigParser) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        parser.write(handle)


def load_plugins() -> dict[str, PluginEntry]:
    """Return the enabled plugins keyed by format name (``{}`` when none)."""
    parser = _read()
    return {
        section[len(_SECTION_PREFIX) :]: PluginEntry.from_dict(parser[section])
        for section in parser.sections()
        if section.startswith(_SECTION_PREFIX)
    }


def get_plugin(name: str) -> PluginEntry | None:
    """Return the stored entry for *name*, or ``None`` when not enabled."""
    parser = _read()
    section = _SECTION_PREFIX + name
    if not parser.has_section(section):
        return None
    return PluginEntry.from_dict(parser[section])


def set_plugin(name: str, entry: PluginEntry) -> None:
    """Record (or replace) the entry for *name* and persist."""
    parser = _read()
    parser[_SECTION_PREFIX + name] = entry.to_dict()
    _write(parser)


def remove_plugin(name: str) -> bool:
    """Drop the entry for *name*; return True if one was removed."""
    parser = _read()
    section = _SECTION_PREFIX + name
    if not parser.has_section(section):
        return False
    parser.remove_section(section)
    _write(parser)
    return True
