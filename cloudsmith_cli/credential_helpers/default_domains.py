# Copyright 2026 Cloudsmith Ltd
"""Built-in Cloudsmith service hosts, with a trusted-config override.

The table below lists the standard ``*.cloudsmith.io`` service hosts and the
package format each one serves. A deployment with its own package-serving
domains — dedicated or on-premise — can replace the table via a ``[domains]``
section in ``config.ini``, mapping hostname to package format.

The override is honoured only from trusted locations. ``config.ini`` is
searched in the current working directory first (``cli/config.py``), so a
``config.ini`` committed to a repository is attacker-controlled input; this
module therefore never reads the domain table from a directory-relative
config, mirroring the split ``_guard_untrusted_endpoints``
(``cli/decorators.py``) already applies to ``api_host``/``api_proxy``.
"""

from __future__ import annotations

import configparser
import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ..cli.config import ConfigReader
from .backends import BackendKind

logger = logging.getLogger(__name__)


class DomainType(str, Enum):
    """What a Cloudsmith host is for.

    A host that serves a single package format speaks that format's native
    protocol (``NATIVE_API``); the two format-less hosts are the download CDN
    and the generic upload endpoint.
    """

    DOWNLOAD = "download"
    UPLOAD = "upload"
    NATIVE_API = "native_api"


def format_for_backend_kind(backend_kind: int | None) -> str | None:
    """Return the package format a backend kind serves, or None.

    A host with no backend kind serves no single format and resolves to
    ``None``. :class:`BackendKind` is a hand-maintained mirror of the
    server-side enum, so a format the CLI does not know yet renders as
    ``unknown`` rather than breaking its caller.
    """
    if backend_kind is None:
        return None

    try:
        return BackendKind(backend_kind).name.lower()
    except ValueError:
        return "unknown"


def domain_type_for_backend_kind(backend_kind: int | None) -> DomainType:
    """Classify a host from its backend kind.

    Compares against ``None`` rather than testing truthiness: ``BackendKind.DEB``
    is ``0``, and a falsy check would classify it as a download host.
    """
    if backend_kind is None:
        return DomainType.DOWNLOAD
    return DomainType.NATIVE_API


@dataclass(frozen=True)
class DefaultDomain:
    """A built-in or config-declared default Cloudsmith host."""

    host: str
    backend_kind: int | None
    domain_type: DomainType = DomainType.NATIVE_API

    def __post_init__(self) -> None:
        if (
            self.backend_kind is not None
            and self.domain_type is not DomainType.NATIVE_API
        ):
            raise ValueError(
                f"A backend kind is only possible on a NATIVE_API host: "
                f"{self.host} is {self.domain_type.value}"
            )

    @property
    def format_label(self) -> str | None:
        """The package format this host serves, or None for no single format."""
        return format_for_backend_kind(self.backend_kind)


BUILTIN_DOMAINS: tuple[DefaultDomain, ...] = (
    DefaultDomain("cargo.cloudsmith.io", BackendKind.CARGO),
    DefaultDomain("composer.cloudsmith.io", BackendKind.COMPOSER),
    DefaultDomain("conan.cloudsmith.io", BackendKind.CONAN),
    DefaultDomain("conda.cloudsmith.io", BackendKind.CONDA),
    DefaultDomain("dart.cloudsmith.io", BackendKind.DART),
    DefaultDomain("dl.cloudsmith.io", None, DomainType.DOWNLOAD),
    DefaultDomain("docker.cloudsmith.io", BackendKind.DOCKER),
    DefaultDomain("generic.cloudsmith.io", BackendKind.GENERIC),
    DefaultDomain("golang.cloudsmith.io", BackendKind.GO),
    DefaultDomain("helm.oci.cloudsmith.io", BackendKind.HELM),
    DefaultDomain("hex.cloudsmith.io", BackendKind.HEX),
    DefaultDomain("huggingface.cloudsmith.io", BackendKind.HUGGINGFACE),
    DefaultDomain("maven.cloudsmith.io", BackendKind.MAVEN),
    DefaultDomain("nix.cloudsmith.io", BackendKind.NIX),
    DefaultDomain("npm.cloudsmith.io", BackendKind.NPM),
    DefaultDomain("nuget.cloudsmith.io", BackendKind.NUGET),
    DefaultDomain("python.cloudsmith.io", BackendKind.PYTHON),
    DefaultDomain("ruby.cloudsmith.io", BackendKind.RUBY),
    DefaultDomain("swift.cloudsmith.io", BackendKind.SWIFT),
    DefaultDomain("terraform.cloudsmith.io", BackendKind.TERRAFORM),
    DefaultDomain("upload.cloudsmith.io", None, DomainType.UPLOAD),
)


def builtin_host(backend_kind: int) -> str:
    """Return the built-in Cloudsmith service host for `backend_kind`.

    Raises ValueError for formats served only via the CDN, which have no
    dedicated built-in host.
    """
    for domain in BUILTIN_DOMAINS:
        if domain.backend_kind == backend_kind:
            return domain.host
    raise ValueError(f"No built-in Cloudsmith host for backend kind {backend_kind}")


def builtin_host_for_type(domain_type: DomainType) -> str:
    """Return the single built-in Cloudsmith host serving `domain_type`.

    Raises ValueError for NATIVE_API, which many hosts share - resolve those by
    backend kind with :func:`builtin_host` instead.
    """
    if domain_type is DomainType.NATIVE_API:
        raise ValueError(
            "NATIVE_API is served by many hosts; resolve it with builtin_host()"
        )
    for domain in BUILTIN_DOMAINS:
        if domain.domain_type is domain_type:
            return domain.host
    raise ValueError(f"No built-in Cloudsmith host of type {domain_type.value}")


def _resolve_backend_kind(label: str) -> int | None:
    """Resolve a config-declared label to a BackendKind member, if any."""
    if not label:
        return None
    return BackendKind.__members__.get(label.upper())


def _domain_from_config_entry(host: str, label: str) -> DefaultDomain:
    """Build a DefaultDomain from one ``[domains]`` ``host = label`` entry.

    A label that does not resolve to a BackendKind is dropped: a host without
    a backend kind serves no single format, so it becomes a formatless
    download host.
    """
    backend_kind = _resolve_backend_kind(label)
    return DefaultDomain(
        host=host,
        backend_kind=backend_kind,
        domain_type=domain_type_for_backend_kind(backend_kind),
    )


def _config_candidates(*, trusted: bool) -> list[Path]:
    """Return candidate config.ini paths from ConfigReader's search locations.

    The locations are click's, via ``ConfigReader``, rather than restated here.
    Its search path lists the current directory first, so absolute entries are
    the trusted ones and directory-relative entries are not.

    Absolute filenames are skipped: ``load_config`` prepends an explicit
    ``--config-file`` to ``config_files``, and joining an absolute path onto a
    search directory would yield that path under every location - handing a
    trusted file to the untrusted scan. Callers receive an explicit config
    directly instead (see :func:`load_default_domains`).
    """
    filenames = [
        filename
        for filename in ConfigReader.config_files
        if not os.path.isabs(filename)
    ]
    return [
        Path(directory) / filename
        for directory in ConfigReader.config_searchpath
        if os.path.isabs(directory) is trusted
        for filename in filenames
    ]


def _trusted_config_path() -> Path | None:
    """Return the first existing config.ini from a trusted location, if any."""
    for candidate in _config_candidates(trusted=True):
        if candidate.exists():
            return candidate
    return None


def _read_domains_section(path: Path) -> configparser.SectionProxy | None:
    """Return the ``[domains]`` section at `path`, or None if absent/unreadable.

    ``[domains]`` maps arbitrary hostnames to formats, so its keys cannot be
    declared as a click_configfile section schema the way ``[default]`` is; it
    is read with configparser directly.
    """
    parser = configparser.ConfigParser()
    try:
        read_files = parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error) as exc:
        logger.debug("Failed to read config file %s: %s", path, exc)
        return None

    if not read_files or not parser.has_section("domains"):
        return None
    return parser["domains"]


def _domains_from_config(path: Path) -> list[DefaultDomain] | None:
    """Parse a [domains] section at `path`, or None if absent/unreadable."""
    section = _read_domains_section(path)
    if section is None:
        return None

    domains = [
        _domain_from_config_entry(host, label) for host, label in section.items()
    ]
    return sorted(domains, key=lambda domain: domain.host)


def load_default_domains(config_path: Path | str | None = None) -> list[DefaultDomain]:
    """Return the default domain table, honouring a trusted config override.

    When `config_path` is given, that file is read directly. Otherwise
    `config.ini` is looked up in ConfigReader's absolute search locations only,
    never the current working directory. A malformed or unreadable file falls
    back to the built-in table.
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
    return any(
        _read_domains_section(candidate) is not None
        for candidate in _config_candidates(trusted=False)
    )
