# Copyright 2026 Cloudsmith Ltd
"""Installer for the Docker credential helper.

Manages writing/removing the ``docker-credential-cloudsmith`` launcher and
patching ``~/.docker/config.json`` to enable the helper for Cloudsmith
registry hosts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ...core.cache_utils import merge_json_file
from ..launchers import is_on_path, remove_launcher, resolve_bin_dir, write_launcher


def _docker_config_path() -> Path:
    """Return the path to the Docker client configuration file.

    Respects the ``DOCKER_CONFIG`` environment variable; otherwise returns
    the platform default ``~/.docker/config.json``.
    """
    docker_config_env = os.environ.get("DOCKER_CONFIG")
    if docker_config_env:
        return Path(docker_config_env) / "config.json"
    return Path.home() / ".docker" / "config.json"


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
    TARGET_CMD = "cloudsmith credential-helper docker"
    HELPER_VALUE = "cloudsmith"
    DEFAULT_HOST = "docker.cloudsmith.io"

    name = "docker"
    summary = "Docker credential helper for Cloudsmith registries"

    def install(
        self,
        *,
        bin_dir: str | None = None,
        domains: tuple[str, ...] = (),
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

        # De-duplicate while preserving order
        seen: set[str] = set()
        hosts: list[str] = []
        for h in [self.DEFAULT_HOST, *domains]:
            if h not in seen:
                seen.add(h)
                hosts.append(h)

        def mutate(config: dict) -> None:
            config.setdefault("credHelpers", {})
            for host in hosts:
                config["credHelpers"][host] = self.HELPER_VALUE

        actions: list[str] = []

        if dry_run:
            if os.name == "nt":
                launcher_path = target_dir / f"{self.LAUNCHER_NAME}.cmd"
            else:
                launcher_path = target_dir / self.LAUNCHER_NAME
            actions.append(f"would write launcher {launcher_path}")

            would_change = merge_json_file(config_path, mutate, dry_run=True)
            for host in hosts:
                if would_change:
                    actions.append(
                        f"would set credHelpers[{host!r}]={self.HELPER_VALUE!r}"
                        f" in {config_path}"
                    )
                else:
                    actions.append(
                        f"credHelpers[{host!r}] already set"
                        f" in {config_path} (no change)"
                    )
            return actions

        # Real install
        launcher_path = write_launcher(target_dir, self.LAUNCHER_NAME, self.TARGET_CMD)
        actions.append(f"wrote launcher {launcher_path}")

        changed = merge_json_file(config_path, mutate)
        if changed:
            for host in hosts:
                actions.append(
                    f"set credHelpers[{host!r}]={self.HELPER_VALUE!r}"
                    f" in {config_path}"
                )
        else:
            actions.append(f"config.json already up to date ({config_path})")

        if not is_on_path(target_dir):
            actions.append(
                f"WARNING: {target_dir} is not on PATH — "
                "add it to your PATH so Docker can find docker-credential-cloudsmith"
            )

        return actions

    def uninstall(self, *, dry_run: bool = False) -> list[str]:
        """Uninstall the Docker credential helper.

        Removes the launcher binary and strips Cloudsmith-managed entries from
        ``~/.docker/config.json``.

        Parameters
        ----------
        dry_run:
            When ``True``, return planned actions without writing any files.

        Returns
        -------
        list[str]
            Human-readable descriptions of actions taken (or planned).
        """
        target_dir = resolve_bin_dir()
        config_path = _docker_config_path()

        def mutate(config: dict) -> None:
            helpers = config.get("credHelpers", {})
            removed = [k for k, v in helpers.items() if v == self.HELPER_VALUE]
            for key in removed:
                del helpers[key]
            if removed and not config["credHelpers"]:
                del config["credHelpers"]

        actions: list[str] = []

        if os.name == "nt":
            launcher_path = target_dir / f"{self.LAUNCHER_NAME}.cmd"
        else:
            launcher_path = target_dir / self.LAUNCHER_NAME

        if dry_run:
            if launcher_path.exists():
                actions.append(f"would remove launcher {launcher_path}")
            else:
                actions.append(
                    f"launcher not found at {launcher_path} (nothing to remove)"
                )

            would_change = merge_json_file(config_path, mutate, dry_run=True)
            if would_change:
                actions.append(
                    f"would remove credHelpers entries with value"
                    f" {self.HELPER_VALUE!r} from {config_path}"
                )
            else:
                actions.append(f"no credHelpers entries to remove from {config_path}")
            return actions

        # Real uninstall
        removed = remove_launcher(target_dir, self.LAUNCHER_NAME)
        if removed:
            actions.append(f"removed launcher {launcher_path}")
        else:
            actions.append(f"launcher not found at {launcher_path} (nothing to remove)")

        changed = merge_json_file(config_path, mutate)
        if changed:
            actions.append(
                f"removed credHelpers entries with value"
                f" {self.HELPER_VALUE!r} from {config_path}"
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
                The :class:`~pathlib.Path` of the launcher if it exists,
                else ``None``.
            ``"hosts"``
                List of hostnames in ``config.json``'s ``credHelpers`` block
                whose value equals ``"cloudsmith"``.
        """
        target_dir = resolve_bin_dir()
        if os.name == "nt":
            launcher_path: Path | None = target_dir / f"{self.LAUNCHER_NAME}.cmd"
        else:
            launcher_path = target_dir / self.LAUNCHER_NAME

        if launcher_path is not None and not launcher_path.exists():
            launcher_path = None

        config_path = _docker_config_path()
        hosts: list[str] = []
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    helpers = data.get("credHelpers", {})
                    hosts = [k for k, v in helpers.items() if v == self.HELPER_VALUE]
            except (json.JSONDecodeError, OSError):
                pass

        return {"launcher": launcher_path, "hosts": hosts}
