# Copyright 2026 Cloudsmith Ltd
"""Built-in Cloudsmith service hosts, with a trusted-config override.

``credential-helper domains`` is the single authority a keyring backend
consults to decide which hosts may receive a Cloudsmith token. The built-in
table below lists the standard ``*.cloudsmith.io`` hosts; a deployment with
its own custom package-serving domains can replace that table via a
``[domains]`` section in ``config.ini`` — but only when that file comes from a
trusted location.

``config.ini`` is searched in the current working directory first
(``cli/config.py``), so a ``config.ini`` committed to a repository is
attacker-controlled input. Honouring a ``[domains]`` section from a
directory-relative config would let a malicious repo declare an arbitrary
host a Cloudsmith host and harvest a live credential. This module therefore
reads ``config.ini`` only from trusted locations, mirroring the split
``_guard_untrusted_endpoints`` (``cli/decorators.py``) already applies to
``api_host``/``api_proxy``.
"""

from __future__ import annotations

import configparser
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from ..cli.config import get_default_config_path
from .backends import BackendKind

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DefaultDomain:
    """A built-in or config-declared default Cloudsmith host."""

    host: str
    format_label: str
    backend_kind: int | None


BUILTIN_DOMAINS: tuple[DefaultDomain, ...] = (
    DefaultDomain("cargo.cloudsmith.io", "cargo", BackendKind.CARGO),
    DefaultDomain("composer.cloudsmith.io", "composer", BackendKind.COMPOSER),
    DefaultDomain("conan.cloudsmith.io", "conan", BackendKind.CONAN),
    DefaultDomain("conda.cloudsmith.io", "conda", BackendKind.CONDA),
    DefaultDomain("dart.cloudsmith.io", "dart", BackendKind.DART),
    DefaultDomain("dl.cloudsmith.io", "-", None),
    DefaultDomain("docker.cloudsmith.io", "docker", BackendKind.DOCKER),
    DefaultDomain("generic.cloudsmith.io", "generic", BackendKind.GENERIC),
    DefaultDomain("golang.cloudsmith.io", "go", BackendKind.GO),
    DefaultDomain("helm.oci.cloudsmith.io", "helm", BackendKind.HELM),
    DefaultDomain("hex.cloudsmith.io", "hex", BackendKind.HEX),
    DefaultDomain("huggingface.cloudsmith.io", "huggingface", BackendKind.HUGGINGFACE),
    DefaultDomain("maven.cloudsmith.io", "maven", BackendKind.MAVEN),
    DefaultDomain("nix.cloudsmith.io", "nix", BackendKind.NIX),
    DefaultDomain("npm.cloudsmith.io", "npm", BackendKind.NPM),
    DefaultDomain("nuget.cloudsmith.io", "nuget", BackendKind.NUGET),
    DefaultDomain("python.cloudsmith.io", "python", BackendKind.PYTHON),
    DefaultDomain("ruby.cloudsmith.io", "ruby", BackendKind.RUBY),
    DefaultDomain("swift.cloudsmith.io", "swift", BackendKind.SWIFT),
    DefaultDomain("terraform.cloudsmith.io", "terraform", BackendKind.TERRAFORM),
    DefaultDomain("upload.cloudsmith.io", "-", None),
)


def _resolve_backend_kind(label: str) -> int | None:
    """Resolve a config-declared label to a BackendKind member, if any."""
    if not label:
        return None
    return BackendKind.__members__.get(label.upper())


def _trusted_config_path() -> Path | None:
    """Return the first existing config.ini from a trusted location, if any."""
    for directory in (get_default_config_path(), os.path.expanduser("~/.cloudsmith")):
        candidate = Path(directory) / "config.ini"
        if candidate.exists():
            return candidate
    return None


def _domains_from_config(path: Path) -> list[DefaultDomain] | None:
    """Parse a [domains] section at `path`, or None if absent/unreadable."""
    parser = configparser.ConfigParser()
    try:
        read_files = parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error) as exc:
        logger.debug("Failed to read config file %s: %s", path, exc)
        return None

    if not read_files or not parser.has_section("domains"):
        return None

    domains = [
        DefaultDomain(
            host=host,
            format_label=label if label else "-",
            backend_kind=_resolve_backend_kind(label),
        )
        for host, label in parser.items("domains")
    ]
    return sorted(domains, key=lambda domain: domain.host)


def load_default_domains(config_path: Path | str | None = None) -> list[DefaultDomain]:
    """Return the default domain table, honouring a trusted config override.

    When `config_path` is given, that file is read directly. Otherwise
    `config.ini` is looked up in trusted locations only -
    `get_default_config_path()` then `~/.cloudsmith` - never the current
    working directory. A malformed or unreadable file falls back to the
    built-in table.
    """
    if config_path is not None:
        path = Path(config_path)
    else:
        path = _trusted_config_path()

    if path is None:
        return list(BUILTIN_DOMAINS)

    domains = _domains_from_config(path)
    if domains is None:
        return list(BUILTIN_DOMAINS)

    return domains


def untrusted_config_declares_domains() -> bool:
    """True if a directory-relative config.ini declares a [domains] section.

    Such a section is deliberately ignored: config.ini is searched in the
    current working directory first, so a repository can ship one, and this
    command decides which hosts may receive a Cloudsmith token. Honouring it
    would let a malicious repo harvest a live credential - the same vector
    ``_guard_untrusted_endpoints`` closes for api_host. The caller warns so
    the omission is visible rather than silent.
    """
    parser = configparser.ConfigParser()
    try:
        read_files = parser.read("config.ini", encoding="utf-8")
    except (OSError, configparser.Error) as exc:
        logger.debug("Failed to read cwd config.ini: %s", exc)
        return False

    return bool(read_files) and parser.has_section("domains")
