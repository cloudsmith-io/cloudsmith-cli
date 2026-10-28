# Copyright 2026 Cloudsmith Ltd
"""Installer for the Docker credential helper.

Manages writing/removing the ``docker-credential-cloudsmith*`` launchers and
patching ``~/.docker/config.json`` to enable the helper for Cloudsmith
registry hosts.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
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
    parse_launcher_env,
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


# The profile and the Workspace of an install name its helper.
_SCOPE_ENVVARS = ("CLOUDSMITH_PROFILE", "CLOUDSMITH_WORKSPACE")
_SCOPE_FLAGS = ("-P", "-w")


class HelperScopeConflict(ValueError):
    """Raised when the launcher of another profile or Workspace has the name."""


def _helper_name(scope: tuple[str | None, ...]) -> str:
    """Return the ``credHelpers`` value for an install with this scope.

    Each profile and Workspace gets its own launcher, so that installs for
    different configurations can coexist.
    """
    segments = [
        re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
        for value in scope
        if value
    ]
    return "-".join(["cloudsmith", *filter(None, segments)])


def _check_scope(launcher_path: Path, scope: tuple[str | None, ...]) -> None:
    """Raise :class:`HelperScopeConflict` if another scope wrote the launcher.

    Different scopes can give the same name, for example ``-P acme`` and
    ``-w acme``.
    """
    if not launcher_path.exists():
        return
    env = parse_launcher_env(launcher_path.read_text(encoding="utf-8"))
    installed = tuple(env.get(name) for name in _SCOPE_ENVVARS)
    if installed != scope:
        flags = "".join(
            f" {flag} {shlex.quote(value)}"
            for flag, value in zip(_SCOPE_FLAGS, installed)
            if value
        )
        raise HelperScopeConflict(
            f"{launcher_path} is the helper of an install with a different"
            " profile or Workspace. To remove it, run: cloudsmith"
            f" credential-helper uninstall docker{flags}"
        )


def _is_cloudsmith_helper(value) -> bool:
    return value == "cloudsmith" or str(value).startswith("cloudsmith-")


def _launcher_name(helper: str) -> str:
    return f"docker-credential-{helper}"


def _launcher_path(target_dir: Path, helper: str) -> Path:
    name = _launcher_name(helper)
    return target_dir / (f"{name}.cmd" if is_windows() else name)


class DockerInstaller:
    """Manages installation of the Docker credential helper for Cloudsmith.

    This installer writes a ``docker-credential-cloudsmith*`` launcher binary
    and patches ``~/.docker/config.json`` to route the configured registry
    hosts through the Cloudsmith credential helper.

    Usage::

        installer = DockerInstaller()
        actions = installer.install(domains=["my-registry.example.com"])
        for action in actions:
            print(action)
    """

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
        launcher_env:
            ``CLOUDSMITH_*`` settings that the launcher sets.  The profile and
            the Workspace in them name the helper.
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
        scope = tuple(launcher_env.get(name) for name in _SCOPE_ENVVARS)
        helper = _helper_name(scope)
        launcher_name = _launcher_name(helper)
        _check_scope(_launcher_path(target_dir, helper), scope)

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
        scope = (profile, workspace)
        helper = _helper_name(scope)
        launcher_name = _launcher_name(helper)
        _check_scope(_launcher_path(target_dir, helper), scope)
        # A missing config has no entries. A merge would create an empty file.
        config_exists: bool = config_path.exists()

        def mutate(config: dict[str, object]) -> None:
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

            would_change = config_exists and merge_config_file(
                config_path, mutate, dry_run=True
            )
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

        changed = config_exists and merge_config_file(config_path, mutate)
        if changed:
            actions.append(
                f"removed credHelpers entries with value {helper!r} from {config_path}"
            )
        else:
            actions.append(f"no credHelpers entries to remove from {config_path}")

        return actions

    def statuses(self) -> list[dict]:
        """Return the status of each Cloudsmith helper in ``config.json``.

        Returns
        -------
        list[dict]
            One dict for each ``cloudsmith`` or ``cloudsmith-*`` helper, in the
            order of the ``credHelpers`` block, with keys:

            ``"launcher"``
                The path of the launcher of the helper, or ``None`` if it does
                not exist.
            ``"hosts"``
                List of hostnames that use the helper.

            Without such a helper, the list has only the unscoped helper.
        """
        config_path = _docker_config_path()
        hosts_by_helper: dict[str, list[str]] = {}
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for host, helper in data.get("credHelpers", {}).items():
                        if _is_cloudsmith_helper(helper):
                            hosts_by_helper.setdefault(helper, []).append(host)
            except (json.JSONDecodeError, OSError):
                pass

        target_dir = resolve_bin_dir()
        statuses = []
        for helper, hosts in (hosts_by_helper or {"cloudsmith": []}).items():
            launcher_path = _launcher_path(target_dir, helper)
            statuses.append(
                {
                    "launcher": str(launcher_path) if launcher_path.exists() else None,
                    "hosts": hosts,
                }
            )
        return statuses
