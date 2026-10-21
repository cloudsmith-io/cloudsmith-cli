# Copyright 2026 Cloudsmith Ltd
"""Installer for the Docker credential helper.

Manages writing/removing the ``docker-credential-cloudsmith`` launcher and
patching ``~/.docker/config.json`` to enable the helper for Cloudsmith
registry hosts.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ...core.cache_utils import merge_config_file
from ..backends import BackendKind
from ..common import path_warning
from ..domains import get_format_domains
from ..launchers import (
    helper_command,
    is_on_path,
    is_windows,
    remove_launcher,
    resolve_bin_dir,
    write_launcher,
)

if TYPE_CHECKING:
    from ...core.credentials.models import CredentialResult

logger = logging.getLogger(__name__)


def _docker_config_path() -> Path:
    """Return the path to the Docker client configuration file.

    Respects the ``DOCKER_CONFIG`` environment variable; otherwise returns
    the platform default ``~/.docker/config.json``.
    """
    docker_config_env = os.environ.get("DOCKER_CONFIG")
    if docker_config_env:
        return Path(docker_config_env) / "config.json"
    return Path.home() / ".docker" / "config.json"


def _helper_name(profile: str | None, workspace: str | None) -> str:
    """Return the ``credHelpers`` value for an install with these settings.

    Each profile and Workspace gets its own launcher, so that installs for
    different configurations can coexist.
    """
    segments = [
        re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
        for value in (profile, workspace)
        if value
    ]
    return "-".join(["cloudsmith", *filter(None, segments)])


def _is_cloudsmith_helper(value) -> bool:
    return value == "cloudsmith" or str(value).startswith("cloudsmith-")


def _launcher_path(target_dir: Path, helper: str) -> Path:
    name = f"docker-credential-{helper}"
    return target_dir / (f"{name}.cmd" if is_windows() else name)


class DockerInstaller:
    """Manages installation of the Docker credential helper for Cloudsmith.

    This installer writes a ``docker-credential-cloudsmith`` launcher binary
    and patches ``~/.docker/config.json`` to route the configured registry
    hosts through the Cloudsmith credential helper.

    Usage::

        installer = DockerInstaller()
        actions = installer.install(domains=["my-registry.example.com"])
        for action in actions:
            print(action)
    """

    LAUNCHER_NAME = "docker-credential-cloudsmith"
    DEFAULT_HOST = "docker.cloudsmith.io"
    # Docker runs the helper from Docker Desktop, IDEs and other shells, so
    # the launcher keeps the install-time settings.
    KEEPS_INSTALL_TIME_SETTINGS = True

    name = "docker"
    summary = "Docker credential helper for Cloudsmith registries"

    def install(
        self,
        *,
        bin_dir: str | None = None,
        domains: tuple[str, ...] = (),
        discover: bool = True,
        refresh: bool = False,
        org: str | None = None,
        credential: CredentialResult | None = None,
        api_host: str | None = None,
        profile: str | None = None,
        workspace: str | None = None,
        launcher_env: dict[str, str] | None = None,
        dry_run: bool = False,
    ) -> list[str]:
        """Install the Docker credential helper.

        Writes the launcher binary and registers Cloudsmith registry hosts in
        ``~/.docker/config.json``.

        Parameters
        ----------
        bin_dir:
            Override for the directory to install the launcher.  Defaults to
            :func:`resolve_bin_dir` auto-detection.
        domains:
            Additional registry hostnames to configure (in addition to the
            default ``docker.cloudsmith.io``).
        discover:
            When ``True`` (default), attempt to auto-discover Docker custom
            domains via the Cloudsmith API.  Discovery is best-effort and never
            prevents the defaults from being registered.
        refresh:
            When ``True``, bypass the domain cache and fetch fresh data from
            the API.  Only meaningful when *discover* is also ``True``.
        org:
            Cloudsmith organisation slug used for custom-domain discovery.
        credential:
            Resolved credential used for custom-domain discovery.
        api_host:
            Cloudsmith API host URL override.
        profile, workspace:
            The install-time profile and Workspace, which name the helper.
        launcher_env:
            ``CLOUDSMITH_*`` settings that the launcher sets.
        dry_run:
            When ``True``, compute and return planned actions without writing
            any files.

        Returns
        -------
        list[str]
            Human-readable descriptions of actions taken (or planned, when
            *dry_run* is ``True``).
        """
        target_dir = resolve_bin_dir(bin_dir)
        config_path = _docker_config_path()
        launcher_env = launcher_env or {}
        helper = _helper_name(profile, workspace)
        launcher_name = f"docker-credential-{helper}"

        actions: list[str] = []

        hosts: list[str] = [*domains]
        discovered: list[str] = []

        # --- Custom-domain auto-discovery (best-effort) ---
        if discover:
            if dry_run:
                # Discovery queries the API and refreshes the on-disk domain
                # cache, neither of which a "no changes" preview may do.
                actions.append("skipped custom-domain auto-discovery (dry run)")
            elif org and credential and credential.api_key:
                # Discovery boundary: network/SDK errors must never abort the
                # default install.  ApiException is already handled inside
                # get_format_domains; this broad catch is the deliberate outer
                # boundary (consistent with "boundary catches, library stays clean").
                # Note: BaseException subclasses (KeyboardInterrupt/SystemExit)
                # intentionally propagate — they are not caught by `except Exception`.
                try:
                    discovered = get_format_domains(
                        org,
                        BackendKind.DOCKER,
                        credential=credential,
                        api_host=api_host,
                        refresh=refresh,
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    # Discovery is best-effort: never let it abort the install of
                    # the defaults.  (Network/SDK errors degrade to a warning;
                    # ApiException is already handled inside.)
                    actions.append(
                        f"WARNING: custom-domain auto-discovery failed: {exc}"
                    )
                    discovered = []
                new_hosts = [
                    h for h in discovered if h not in (*hosts, self.DEFAULT_HOST)
                ]
                hosts.extend(discovered)
                actions.append(
                    f"discovered {len(new_hosts)} new Docker custom domain(s)"
                )
            else:
                logger.debug(
                    "skipped auto-discovery"
                    " (no organization/credentials; pass --no-discover to silence)"
                )

        # The API lists the Cloudsmith-owned hosts with the custom domains, so
        # the default host is needed only when discovery gave no hosts.
        if not discovered:
            hosts.insert(0, self.DEFAULT_HOST)

        # De-duplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for h in hosts:
            if h not in seen:
                seen.add(h)
                deduped.append(h)
        hosts = deduped

        replaced: list[str] = []

        def mutate(config: dict) -> None:
            helpers = config.get("credHelpers")
            if not isinstance(helpers, dict):
                helpers = config["credHelpers"] = {}
            for host in hosts:
                current = helpers.get(host)
                if current != helper and _is_cloudsmith_helper(current):
                    replaced.append(
                        f"WARNING: credHelpers[{host!r}] changes from {current!r}"
                        f" to {helper!r}"
                    )
                helpers[host] = helper

        launcher_settings = (
            [f"launcher sets {', '.join(launcher_env)}"] if launcher_env else []
        )

        if dry_run:
            launcher_path = write_launcher(
                target_dir,
                launcher_name,
                helper_command(self.name),
                dry_run=True,
                env=launcher_env,
            )
            actions.append(f"would write launcher {launcher_path}")
            actions.extend(launcher_settings)

            would_change = merge_config_file(config_path, mutate, dry_run=True)
            for host in hosts:
                if would_change:
                    actions.append(
                        f"would set credHelpers[{host!r}]={helper!r} in {config_path}"
                    )
                else:
                    actions.append(
                        f"credHelpers[{host!r}] already set"
                        f" in {config_path} (no change)"
                    )
            return actions + replaced

        # Real install
        launcher_path = write_launcher(
            target_dir, launcher_name, helper_command(self.name), env=launcher_env
        )
        actions.append(f"wrote launcher {launcher_path}")
        actions.extend(launcher_settings)

        changed = merge_config_file(config_path, mutate)
        if changed:
            actions.extend(
                f"set credHelpers[{host!r}]={helper!r} in {config_path}"
                for host in hosts
            )
        else:
            actions.append(f"config.json already up to date ({config_path})")
        actions.extend(replaced)

        if not is_on_path(target_dir):
            actions.append(
                path_warning(target_dir, "Docker", launcher_name, is_windows())
            )

        return actions

    def uninstall(
        self,
        *,
        bin_dir: str | None = None,
        profile: str | None = None,
        workspace: str | None = None,
        dry_run: bool = False,
    ) -> list[str]:
        """Uninstall the Docker credential helper.

        Removes the launcher binary and strips Cloudsmith-managed entries from
        ``~/.docker/config.json``.

        Parameters
        ----------
        bin_dir:
            Override for the directory where the launcher was installed.
            Defaults to :func:`resolve_bin_dir` auto-detection.  Pass the same
            value that was given to :meth:`install` so the correct launcher file
            is found and removed.
        profile, workspace:
            The settings of the install to remove.  Without them, the helper
            of an install without them is removed.
        dry_run:
            When ``True``, return planned actions without writing any files.

        Returns
        -------
        list[str]
            Human-readable descriptions of actions taken (or planned).
        """
        target_dir = resolve_bin_dir(bin_dir)
        config_path = _docker_config_path()
        helper = _helper_name(profile, workspace)
        launcher_name = f"docker-credential-{helper}"

        def mutate(config: dict) -> None:
            helpers = config.get("credHelpers")
            if not isinstance(helpers, dict):
                return
            removed = [k for k, v in helpers.items() if v == helper]
            for key in removed:
                del helpers[key]
            if removed and not helpers:
                del config["credHelpers"]

        actions: list[str] = []
        launcher_path = _launcher_path(target_dir, helper)

        if dry_run:
            if launcher_path.exists():
                actions.append(f"would remove launcher {launcher_path}")
            else:
                actions.append(
                    f"launcher not found at {launcher_path} (nothing to remove)"
                )

            would_change = merge_config_file(config_path, mutate, dry_run=True)
            if would_change:
                actions.append(
                    f"would remove credHelpers entries with value"
                    f" {helper!r} from {config_path}"
                )
            else:
                actions.append(f"no credHelpers entries to remove from {config_path}")
            return actions

        # Real uninstall
        removed = remove_launcher(target_dir, launcher_name)
        if removed:
            actions.append(f"removed launcher {launcher_path}")
        else:
            actions.append(f"launcher not found at {launcher_path} (nothing to remove)")

        changed = merge_config_file(config_path, mutate)
        if changed:
            actions.append(
                f"removed credHelpers entries with value {helper!r} from {config_path}"
            )
        else:
            actions.append(f"no credHelpers entries to remove from {config_path}")

        return actions

    def status(self) -> dict:
        """Return current installation status.

        Returns
        -------
        dict
            A dict with keys:

            ``"launcher"``
                The path of the launcher that the first host uses, else of
                the unscoped launcher, if it exists.  Else ``None``.
            ``"hosts"``
                List of hostnames in ``config.json``'s ``credHelpers`` block
                that use a ``cloudsmith`` or ``cloudsmith-*`` helper.
        """
        config_path = _docker_config_path()
        helpers: dict = {}
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    helpers = {
                        k: v
                        for k, v in data.get("credHelpers", {}).items()
                        if _is_cloudsmith_helper(v)
                    }
            except (json.JSONDecodeError, OSError):
                pass
        hosts = list(helpers)

        target_dir = resolve_bin_dir()
        candidates = [
            _launcher_path(target_dir, helper)
            for helper in [*helpers.values(), "cloudsmith"]
        ]
        launcher_path = next((path for path in candidates if path.exists()), None)

        return {
            "launcher": str(launcher_path) if launcher_path is not None else None,
            "hosts": hosts,
        }
