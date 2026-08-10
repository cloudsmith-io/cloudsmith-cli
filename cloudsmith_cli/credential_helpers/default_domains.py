# Copyright 2026 Cloudsmith Ltd
"""Built-in Cloudsmith service hosts, with a trusted-config override.

The table below lists the standard ``*.cloudsmith.io`` service hosts and the
package format each one serves. A dedicated deployment, serving packages from
its own domains, can replace the table via a ``[domains]`` section in
``config.ini``, mapping each hostname to the package format it serves, or to
``download``/``upload`` for the two endpoints no format names.

A declared table replaces the built-ins wholesale rather than layering over
them: a host it omits has no default at all, so resolution raises instead of
handing back a ``*.cloudsmith.io`` host the operator never listed.

The override is honoured only from trusted locations. ``config.ini`` is
searched in the current working directory first (``cli/config.py``), so a
``config.ini`` committed to a repository is attacker-controlled input; this
module therefore never reads the domain table from a directory-relative
config, mirroring the split ``_guard_untrusted_endpoints``
(``cli/decorators.py``) already applies to ``api_host``/``api_proxy``. An
explicit ``--config-file`` is a user's direct statement of trust regardless of
where it lives, so it is honoured ahead of the search-path locations.
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
    protocol (``NATIVE_API``); the format-less hosts are the download CDN and
    the generic upload endpoint.
    """

    DOWNLOAD = "download"
    UPLOAD = "upload"
    NATIVE_API = "native_api"


SERVER_DOMAIN_TYPES: dict[int, DomainType] = {
    0: DomainType.DOWNLOAD,
    1: DomainType.UPLOAD,
    3: DomainType.NATIVE_API,
}


def format_for_backend_kind(backend_kind: int | None) -> str | None:
    """Return the package format a backend kind serves, or None.

    A host with no backend kind serves no single format and resolves to
    ``None``. :class:`BackendKind` is hand-maintained, so a format the CLI does
    not know yet renders as ``unknown`` rather than breaking its caller.
    """
    if backend_kind is None:
        return None

    try:
        return BackendKind(backend_kind).name.lower()
    except ValueError:
        return "unknown"


def domain_type_from_server(value: int | str) -> DomainType:
    """Resolve a custom domain's type as the server reported it.

    The server classifies every domain and sends the answer as an integer; the
    on-disk cache stores this enum's own string value. A type this CLI does not
    know yet reads as a download host rather than breaking the listing.
    """
    try:
        if isinstance(value, str):
            return DomainType(value)
        return SERVER_DOMAIN_TYPES[int(value)]
    except (KeyError, TypeError, ValueError):
        logger.debug("Unrecognised domain type %r", value)
        return DomainType.DOWNLOAD


@dataclass(frozen=True)
class DefaultDomain:
    """A built-in or config-declared default Cloudsmith host."""

    host: str
    backend_kind: int | None
    domain_type: DomainType = DomainType.NATIVE_API

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

RESERVED_LABELS: dict[str, DomainType] = {
    "download": DomainType.DOWNLOAD,
    "upload": DomainType.UPLOAD,
}


def _resolve_backend_kind(label: str) -> int | None:
    """Resolve a config-declared label to a BackendKind member, if any."""
    if not label:
        return None
    return BackendKind.__members__.get(label.upper())


def _domain_from_config_entry(host: str, label: str) -> DefaultDomain | None:
    """Build a DefaultDomain from one ``[domains]`` ``host = label`` entry.

    A label names a package format, or one of the two endpoints no format
    names: ``download`` for the CDN and ``upload`` for the generic upload
    endpoint, neither of which has a BackendKind to name it by.

    The label is required. An entry naming nothing recognisable is skipped with
    a warning rather than read as the CDN, since a typo'd format quietly
    serving downloads is far harder to spot than a host that is simply absent.
    """
    normalised = label.strip().lower()

    reserved_type = RESERVED_LABELS.get(normalised)
    if reserved_type is not None:
        return DefaultDomain(host=host, backend_kind=None, domain_type=reserved_type)

    backend_kind = _resolve_backend_kind(normalised)
    if backend_kind is None:
        logger.warning(
            "Ignoring %s in the [domains] section: %r names no package format, "
            "nor download or upload",
            host,
            label,
        )
        return None

    return DefaultDomain(host=host, backend_kind=backend_kind)


def _config_candidates(*, trusted: bool) -> list[Path]:
    """Return candidate config.ini paths from ConfigReader's search locations.

    The search path lists the current directory first, so absolute entries are
    the trusted ones and directory-relative entries are not.

    Absolute filenames are skipped. Joining one onto a search directory would
    yield that same path under every location, handing a trusted file to the
    untrusted scan; :func:`_explicit_config_candidate` reads it instead.
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


def _explicit_config_candidate() -> Path | None:
    """Return the explicit ``--config-file`` entry in ``config_files``, if any.

    ``ConfigReader.load_config`` prepends an absolute path here when
    ``--config-file`` names a file; a directory goes to ``config_searchpath``
    instead and is covered by :func:`_config_candidates`. The entry is
    explicit user intent, so it is trusted.
    """
    for filename in ConfigReader.config_files:
        if os.path.isabs(filename):
            return Path(filename)
    return None


def _trusted_domains() -> list[DefaultDomain] | None:
    """Return the [domains] table from the first trusted config declaring one.

    An explicit ``--config-file`` is checked ahead of the search-path
    candidates. Declaring a table is what counts, not existing: a trusted
    ``config.ini`` holding only ``[default]`` api settings must not mask a
    ``[domains]`` section in a later candidate.
    """
    candidates = []
    explicit = _explicit_config_candidate()
    if explicit is not None:
        candidates.append(explicit)
    candidates.extend(_config_candidates(trusted=True))

    for candidate in candidates:
        domains = _domains_from_config(candidate)
        if domains is not None:
            return domains
    return None


def _read_domains_section(path: Path) -> configparser.SectionProxy | None:
    """Return the ``[domains]`` section at `path`, or None if absent/unreadable.

    ``[domains]`` maps arbitrary hostnames to formats, so its keys cannot be
    declared as a click_configfile section schema the way ``[default]`` is; it
    is read with configparser directly.

    A domain table is data, not a template, so interpolation is off and a ``%``
    in a format label is a literal.
    """
    parser = configparser.ConfigParser(interpolation=None)
    try:
        read_files = parser.read(path, encoding="utf-8")
    except (OSError, UnicodeDecodeError, configparser.Error) as exc:
        logger.debug("Failed to read config file %s: %s", path, exc)
        return None

    if not read_files or not parser.has_section("domains"):
        return None
    return parser["domains"]


def _domains_from_config(path: Path) -> list[DefaultDomain] | None:
    """Parse a [domains] section at `path`, or None if it declares no host.

    A section whose every entry was skipped reads as no table at all rather
    than as an empty one, so a wholly unusable declaration falls back to the
    built-in hosts instead of leaving the caller with nothing to publish to.
    """
    section = _read_domains_section(path)
    if section is None:
        return None

    domains = [
        domain
        for host, label in section.items()
        if (domain := _domain_from_config_entry(host, label)) is not None
    ]
    return sorted(domains, key=lambda domain: domain.host) or None


def load_default_domains(config_path: Path | str | None = None) -> list[DefaultDomain]:
    """Return the default domain table, honouring a trusted config override.

    `config_path` is read ahead of the trusted search locations rather than
    instead of them, so a file holding only ``[default]`` api settings cannot
    mask a deployment's ``[domains]`` table. The search locations are
    ConfigReader's absolute ones, never the current working directory. A
    malformed or unreadable file falls back to the built-in table.
    """
    domains = None
    if config_path is not None:
        domains = _domains_from_config(Path(config_path))
    if domains is None:
        domains = _trusted_domains()

    if domains is None:
        return list(BUILTIN_DOMAINS)

    return domains


def untrusted_config_declares_domains() -> bool:
    """True if a directory-relative config.ini declares a [domains] section.

    Such a section is ignored. config.ini is searched in the current working
    directory first, so a repository can ship one, and this table decides which
    hosts may receive a Cloudsmith token: honouring it would let a malicious
    repo harvest a live credential, the same vector
    ``_guard_untrusted_endpoints`` closes for api_host. The caller warns so the
    omission is visible.
    """
    return any(
        _read_domains_section(candidate) is not None
        for candidate in _config_candidates(trusted=False)
    )
