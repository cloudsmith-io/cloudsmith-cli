# Copyright 2026 Cloudsmith Ltd
"""Persistent state for the Maven credential helper.

Records the repository wrapped ``mvn`` runs authenticate against, as a
``[maven]`` section in ``package-managers.ini`` inside the CLI config directory
(alongside ``config.ini`` / ``credentials.ini``).
"""

from __future__ import annotations

import configparser
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import click

from ...cli.config import get_default_config_path
from ..backends import BackendKind
from ..default_domains import DomainType, default_host, default_host_for_type

DEFAULT_SERVER_ID = "cloudsmith"

_SECTION = "maven"

logger = logging.getLogger(__name__)


def default_download_host() -> str:
    """Return the download-CDN host, honouring a trusted [domains] override.

    Resolved per call rather than at import: a dedicated deployment replaces
    the domain table in its ``config.ini``, and a constant frozen from the
    built-in table would pin every binding to ``*.cloudsmith.io``.
    """
    return default_host_for_type(DomainType.DOWNLOAD)


def default_upload_host() -> str:
    """Return the native Maven upload host, honouring the same override."""
    return default_host(BackendKind.MAVEN)


@dataclass(frozen=True)
class Binding:
    """The repository and hosts wrapped ``mvn`` runs are bound to."""

    owner: str = ""
    repo: str = ""
    download_host: str = field(default_factory=default_download_host)
    upload_host: str = field(default_factory=default_upload_host)
    server_id: str = DEFAULT_SERVER_ID


def config_path() -> Path:
    """Return the path to ``package-managers.ini`` in the CLI config dir."""
    return Path(get_default_config_path()) / "package-managers.ini"


def shims_dir() -> Path:
    """Return the directory that holds package-manager shims on PATH."""
    return Path(get_default_config_path()) / "shims"


def _read() -> configparser.ConfigParser:
    """Return the parsed config, or an empty one when it cannot be read.

    A hand-edited ``package-managers.ini`` must not break every wrapped run:
    the shim intercepts every ``mvn`` on the machine, so letting a parse error
    escape would make Maven unusable machine-wide rather than merely
    unconfigured. An unreadable file reads as no binding, which the runner
    already reports with the command needed to fix it.
    """
    parser = configparser.ConfigParser(interpolation=None)
    path = config_path()
    if not path.exists():
        return parser
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, UnicodeDecodeError, configparser.Error) as exc:
        logger.warning("Ignoring unreadable %s: %s", path, exc)
        return configparser.ConfigParser(interpolation=None)
    return parser


def get_binding() -> Binding | None:
    """Return the stored binding, or ``None`` when Maven is not installed."""
    parser = _read()
    if not parser.has_section(_SECTION):
        return None
    section = parser[_SECTION]
    return Binding(
        **{
            name: section[name]
            for name in (f.name for f in fields(Binding))
            if section.get(name)
        }
    )


def set_binding(binding: Binding) -> None:
    """Record (or replace) the stored binding and persist it."""
    parser = _read()
    parser[_SECTION] = asdict(binding)
    _write(parser)


def remove_binding() -> bool:
    """Drop the stored binding; return True if there was one."""
    parser = _read()
    if not parser.has_section(_SECTION):
        return False
    parser.remove_section(_SECTION)
    _write(parser)
    return True


def _write(parser: configparser.ConfigParser) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with click.open_file(str(path), "w") as handle:
        parser.write(handle)
