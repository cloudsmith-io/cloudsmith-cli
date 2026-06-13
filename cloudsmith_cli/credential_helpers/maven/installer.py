# Copyright 2026 Cloudsmith Ltd
"""Installer for the Maven shell-plugin credential helper.

Writes an ``mvn`` shim into the Cloudsmith shims dir, records the repo binding
and resolved hosts in the CLI config, and surfaces the ``distributionManagement``
snippet needed for ``mvn deploy``.  Download resolution works transparently once
the shims dir is on PATH (via ``credential-helper shell-init``); upload is opt-in.

Maven uses two distinct endpoints, so two custom-domain kinds matter:
- **download** (dependency resolution) goes via the download CDN; its custom
  domains carry ``backend_kind is None`` (the generic download domain).
- **upload** (``distributionManagement``) goes via the native Maven endpoint;
  its custom domains carry ``BackendKind.MAVEN``.
"""

from __future__ import annotations

import logging
from xml.sax.saxutils import escape

from ...templates import render
from ..backends import BackendKind
from ..custom_domains import CustomDomain, get_custom_domains
from ..launchers import is_on_path
from ..shellplugin import config
from ..shellplugin.maven import upload_url
from ..shellplugin.shims import remove_shim, write_shim

logger = logging.getLogger(__name__)

_DISTRIBUTION_MANAGEMENT_TEMPLATE = "maven_distribution_management.xml.tmpl"


def _deploy_snippet(owner: str, repo: str, upload_host: str, registry_id: str) -> str:
    """Return the pom.xml distributionManagement snippet for opt-in deploy."""
    snippet = render(
        _DISTRIBUTION_MANAGEMENT_TEMPLATE,
        server_id=escape(registry_id),
        url=escape(upload_url(owner, repo, upload_host)),
    )
    return (
        "To publish with `mvn deploy`, add this to your pom.xml "
        "(the id must match the server id):\n" + snippet
    )


def _first_host(domains: list[CustomDomain], backend_kind: int | None) -> str | None:
    """Return the first enabled+validated host matching *backend_kind*."""
    for domain in domains:
        if domain.backend_kind == backend_kind and domain.enabled and domain.validated:
            return domain.host
    return None


class MavenInstaller:
    """Installs the Maven shell plugin (shim + config entry)."""

    BINARY_NAME = "mvn"
    name = "maven"
    summary = "Maven shell plugin for Cloudsmith repositories"
    requires_repo = True

    def _discover_domains(
        self,
        *,
        org: str | None,
        api_key: str | None,
        auth_type: str,
        api_host: str | None,
        refresh: bool,
        actions: list[str],
    ) -> list[CustomDomain]:
        """Fetch the org's custom domains (best-effort; failure → WARNING + [])."""
        if not (org and api_key):
            return []
        try:
            return get_custom_domains(
                org,
                api_key=api_key,
                auth_type=auth_type,
                api_host=api_host,
                refresh=refresh,
            )
        except Exception as exc:  # pylint: disable=broad-except
            # Discovery boundary: never let a lookup failure abort the install.
            actions.append(f"WARNING: custom-domain discovery failed: {exc}")
            return []

    def _resolve_hosts(
        self,
        *,
        domains_override: tuple[str, ...],
        discover: bool,
        org: str | None,
        api_key: str | None,
        auth_type: str,
        api_host: str | None,
        refresh: bool,
        actions: list[str],
    ) -> tuple[str, str]:
        """Resolve (cdn_host, upload_host) from overrides, discovery, defaults."""
        discovered: list[CustomDomain] = []
        if discover:
            discovered = self._discover_domains(
                org=org,
                api_key=api_key,
                auth_type=auth_type,
                api_host=api_host,
                refresh=refresh,
                actions=actions,
            )

        if domains_override:
            cdn_host = domains_override[0]
        else:
            cdn_host = _first_host(discovered, None) or config.DEFAULT_CDN_HOST
        upload_host = (
            _first_host(discovered, BackendKind.MAVEN) or config.DEFAULT_UPLOAD_HOST
        )
        return cdn_host, upload_host

    def install(
        self,
        *,
        domains: tuple[str, ...] = (),
        discover: bool = True,
        refresh: bool = False,
        org: str | None = None,
        repo: str | None = None,
        registry_id: str = config.DEFAULT_REGISTRY_ID,
        api_key: str | None = None,
        auth_type: str = "api_key",
        api_host: str | None = None,
        dry_run: bool = False,
    ) -> list[str]:
        """Install the Maven shell plugin; return human-readable actions."""
        owner = org
        actions: list[str] = []

        cdn_host, upload_host = self._resolve_hosts(
            domains_override=domains,
            discover=discover,
            org=owner,
            api_key=api_key,
            auth_type=auth_type,
            api_host=api_host,
            refresh=refresh,
            actions=actions,
        )

        shims_dir = config.shims_dir()
        shim_path = shims_dir / self.BINARY_NAME

        if dry_run:
            actions.append(f"would write shim {shim_path}")
            actions.append(
                f"would configure maven for {owner}/{repo} "
                f"(download {cdn_host}, upload {upload_host})"
            )
            actions.append(
                _deploy_snippet(owner or "", repo or "", upload_host, registry_id)
            )
            return actions

        write_shim(shims_dir, self.BINARY_NAME)
        actions.append(f"wrote shim {shim_path}")

        config.set_plugin(
            self.name,
            config.PluginEntry(
                owner=owner or "",
                repo=repo or "",
                api_host=api_host or config.DEFAULT_API_HOST,
                cdn_host=cdn_host,
                upload_host=upload_host,
                registry_id=registry_id,
            ),
        )
        actions.append(
            f"configured maven for {owner}/{repo} "
            f"(download {cdn_host}, upload {upload_host})"
        )

        if not is_on_path(shims_dir):
            actions.append(
                f"WARNING: {shims_dir} is not on PATH — add it with "
                '`eval "$(cloudsmith credential-helper shell-init)"`'
            )

        actions.append(
            _deploy_snippet(owner or "", repo or "", upload_host, registry_id)
        )
        return actions

    def uninstall(self, *, dry_run: bool = False) -> list[str]:
        """Remove the Maven shim and drop its config entry."""
        shims_dir = config.shims_dir()
        shim_path = shims_dir / self.BINARY_NAME
        actions: list[str] = []

        if dry_run:
            if shim_path.exists():
                actions.append(f"would remove shim {shim_path}")
            else:
                actions.append(f"shim not found at {shim_path} (nothing to remove)")
            if config.get_plugin(self.name) is not None:
                actions.append("would remove maven from the package-manager config")
            else:
                actions.append("maven not configured (nothing to remove)")
            return actions

        if remove_shim(shims_dir, self.BINARY_NAME):
            actions.append(f"removed shim {shim_path}")
        else:
            actions.append(f"shim not found at {shim_path} (nothing to remove)")

        if config.remove_plugin(self.name):
            actions.append("removed maven from the package-manager config")
        else:
            actions.append("maven not configured (nothing to remove)")
        return actions

    def status(self) -> dict:
        """Return shim path (str|None) and configured hosts for `list`."""
        shim_path = config.shims_dir() / self.BINARY_NAME
        launcher = str(shim_path) if shim_path.exists() else None

        entry = config.get_plugin(self.name)
        hosts: list[str] = []
        if entry is not None:
            hosts = [
                f"{entry.owner}/{entry.repo}",
                f"download:{entry.cdn_host}",
                f"upload:{entry.upload_host}",
            ]
        return {"launcher": launcher, "hosts": hosts}
