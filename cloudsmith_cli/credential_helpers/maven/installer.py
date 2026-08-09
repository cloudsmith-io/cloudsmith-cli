# Copyright 2026 Cloudsmith Ltd
"""Installer for the Maven credential helper.

Writes an ``mvn`` shim that re-execs ``cloudsmith exec -- mvn "$@"`` into the
Cloudsmith shims dir, records the repository binding, and prints the
``distributionManagement`` snippet needed for ``mvn deploy``.  Dependency
resolution works transparently once the shims dir is on PATH (via
``credential-helper shell-init``); publishing is opt-in.

Maven uses two distinct endpoints, so two custom-domain kinds matter:
- **download** (dependency resolution) goes via the download CDN; its custom
  domains carry ``backend_kind is None`` (the generic download domain).
- **upload** (``distributionManagement``) goes via the native Maven endpoint;
  its custom domains carry ``BackendKind.MAVEN``.
"""

from __future__ import annotations

import logging
import shutil
from xml.sax.saxutils import escape

from ...core.api.exceptions import ApiException
from ...core.credentials.models import CredentialResult
from ...templates import render
from ..backends import BackendKind
from ..custom_domains import CustomDomain, get_custom_domains, order_by_precedence
from ..default_domains import DomainType
from ..launchers import (
    cloudsmith_command,
    is_frozen,
    is_on_path,
    launcher_filename,
    remove_launcher,
    write_launcher,
)
from . import config
from .runner import BINARY_NAMES
from .settings import upload_url

logger = logging.getLogger(__name__)

BINARY_NAME = BINARY_NAMES[0]

_DISTRIBUTION_MANAGEMENT_TEMPLATE = "maven_distribution_management.xml.tmpl"

_USER_SETTINGS_NOTE = (
    "note: wrapped mvn runs use a generated settings.xml; your "
    "~/.m2/settings.xml (mirrors, proxies, other servers) is not consulted. "
    "Pass your own -s/--settings to mvn to bypass credential injection."
)


def _deploy_snippet(binding: config.Binding) -> str:
    """Return the pom.xml distributionManagement snippet for opt-in deploy."""
    snippet = render(
        _DISTRIBUTION_MANAGEMENT_TEMPLATE,
        server_id=escape(binding.server_id),
        url=escape(upload_url(binding.owner, binding.repo, binding.upload_host)),
    )
    return (
        "To publish with `mvn deploy`, add this to your pom.xml "
        "(the id must match the server id):\n" + snippet
    )


def _discover_domains(
    org: str | None,
    credential: CredentialResult | None,
    api_host: str | None,
    refresh: bool,
    actions: list[str],
) -> list[CustomDomain]:
    """Fetch the org's custom domains (best-effort; failure → WARNING + []).

    The lookup is strict so a failure arrives here as an ApiException rather
    than an empty list: an unreachable API must not read as "this org has no
    custom domains" and silently bind the install to the default hosts.
    """
    if not (org and credential):
        return []
    try:
        return get_custom_domains(
            org, credential=credential, api_host=api_host, refresh=refresh, strict=True
        )
    except ApiException as exc:
        actions.append(f"WARNING: custom-domain discovery failed: {exc}")
        return []


def _select_host(
    domains: list[CustomDomain],
    backend_kind: int | None,
    domain_type: DomainType,
    default_host,
) -> str:
    """Return the host to bind for one endpoint, or the default.

    The backend kind alone does not identify an endpoint — the download CDN
    and the generic upload endpoint both carry ``backend_kind is None`` — so
    the domain type is matched too.  Domains bound to a single repository are
    left out: they need URLs of a different shape, which is its own change.
    Candidates are ranked the way the server ranks overlapping domains, so two
    installs of the same repository agree regardless of discovery order.
    """
    eligible = [
        domain
        for domain in domains
        if domain.backend_kind == backend_kind
        and domain.domain_type is domain_type
        and domain.is_active
        and not domain.repository
    ]
    ordered = order_by_precedence(eligible)
    return ordered[0].host if ordered else default_host()


def _cloudsmith_command_is_unresolvable() -> bool:
    """True when `cloudsmith` cannot be resolved and this is not a frozen build.

    The shim execs ``cloudsmith exec -- mvn``, so an inactive venv makes every
    wrapped ``mvn`` fail machine-wide, not just this shim.  A frozen build
    points the shim at ``sys.executable`` directly, so PATH is irrelevant to it.
    """
    return not is_frozen() and shutil.which("cloudsmith") is None


class MavenInstaller:
    """Installs the Maven credential helper (shim + config entry)."""

    name = "maven"
    summary = "Maven credential helper for Cloudsmith repositories"
    requires_repo = True

    def install(
        self,
        *,
        discover: bool = True,
        refresh: bool = False,
        org: str | None = None,
        repo: str | None = None,
        server_id: str = config.DEFAULT_SERVER_ID,
        credential: CredentialResult | None = None,
        api_host: str | None = None,
        dry_run: bool = False,
    ) -> list[str]:
        """Install the Maven credential helper; return readable actions."""
        actions: list[str] = []
        discovered = (
            _discover_domains(org, credential, api_host, refresh, actions)
            if discover
            else []
        )
        binding = config.Binding(
            owner=org or "",
            repo=repo or "",
            download_host=_select_host(
                discovered, None, DomainType.DOWNLOAD, config.default_download_host
            ),
            upload_host=_select_host(
                discovered,
                BackendKind.MAVEN,
                DomainType.NATIVE_API,
                config.default_upload_host,
            ),
            server_id=server_id,
        )
        description = (
            f"maven for {binding.owner}/{binding.repo} "
            f"(download {binding.download_host}, upload {binding.upload_host})"
        )

        if dry_run:
            actions.append(f"would write shim {_shim_path()}")
            actions.append(f"would configure {description}")
        else:
            actions.extend(self._configure(binding, description))

        actions.append(_USER_SETTINGS_NOTE)
        actions.append(_deploy_snippet(binding))
        return actions

    def _configure(self, binding: config.Binding, description: str) -> list[str]:
        """Persist the binding, write the shim, and warn about the setup."""
        # The binding is persisted first: the shim intercepts every `mvn` on
        # the machine and refuses to run one it has no binding for, so a shim
        # written ahead of a failed set_binding would leave Maven unusable
        # rather than merely uninstalled.
        config.set_binding(binding)
        actions = [f"configured {description}"]

        shims_dir = config.shims_dir()
        actions.append(
            "wrote shim "
            + str(
                write_launcher(
                    shims_dir,
                    BINARY_NAME,
                    cloudsmith_command("exec", "--", BINARY_NAME),
                )
            )
        )

        if not is_on_path(shims_dir):
            actions.append(
                f"WARNING: {shims_dir} is not on PATH — add it with "
                '`eval "$(cloudsmith credential-helper shell-init)"`'
            )
        if _cloudsmith_command_is_unresolvable():
            actions.append(
                "WARNING: the `cloudsmith` command is not on PATH — every "
                "wrapped mvn run will fail until it is; activate the "
                "environment it is installed in"
            )
        return actions

    def uninstall(self, *, dry_run: bool = False) -> list[str]:
        """Remove the Maven shim and drop its config entry."""
        shim = _shim_path()
        shim_absent = f"shim not found at {shim} (nothing to remove)"
        not_configured = "maven not configured (nothing to remove)"
        if dry_run:
            return [
                f"would remove shim {shim}" if shim.exists() else shim_absent,
                (
                    "would remove maven from the package-manager config"
                    if config.get_binding() is not None
                    else not_configured
                ),
            ]
        return [
            (
                f"removed shim {shim}"
                if remove_launcher(config.shims_dir(), BINARY_NAME)
                else shim_absent
            ),
            (
                "removed maven from the package-manager config"
                if config.remove_binding()
                else not_configured
            ),
        ]

    def status(self) -> dict:
        """Return shim path (str|None) and configured hosts for `list`."""
        shim = _shim_path()
        binding = config.get_binding()
        hosts = (
            [
                f"{binding.owner}/{binding.repo}",
                f"download:{binding.download_host}",
                f"upload:{binding.upload_host}",
            ]
            if binding is not None
            else []
        )
        return {"launcher": str(shim) if shim.exists() else None, "hosts": hosts}


def _shim_path():
    """Return the path the ``mvn`` shim is written to on this platform."""
    return config.shims_dir() / launcher_filename(BINARY_NAME)
