# Copyright 2026 Cloudsmith Ltd
"""Installer for the Terraform credentials helper.

Manages writing/removing the ``terraform-credentials-cloudsmith`` launcher and
the ``credentials_helper "cloudsmith"`` block in ``~/.terraformrc`` so Terraform
authenticates to Cloudsmith Terraform registries through the Cloudsmith
credential chain.

Unlike Docker/Cargo/pnpm, Terraform does **not** search ``PATH`` for credentials
helpers — it only looks in its default plugin locations. The launcher is
therefore written into ``~/.terraform.d/plugins`` by default (override with
``--bin-dir``) rather than a PATH directory.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from ..launchers import remove_launcher, write_launcher
from . import terraformrc

logger = logging.getLogger(__name__)


def _terraformrc_path() -> Path:
    """Return the path to Terraform's CLI configuration file.

    Respects ``TF_CLI_CONFIG_FILE`` (Terraform's own override); otherwise
    returns the platform default. On Windows that is ``%APPDATA%/terraform.rc``;
    everywhere else it is ``~/.terraformrc``.
    """
    override = os.environ.get("TF_CLI_CONFIG_FILE")
    if override:
        return Path(override)
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home()
        return base / "terraform.rc"
    return Path.home() / ".terraformrc"


def _default_plugin_dir() -> Path:
    """Return Terraform's conventional user plugin directory.

    ``~/.terraform.d/plugins`` on all platforms — the best-known of Terraform's
    default credentials-helper search locations and writable without elevation.
    """
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home()
        return base / "terraform.d" / "plugins"

    return Path.home() / ".terraform.d" / "plugins"


class TerraformInstaller:
    """Manages installation of the Terraform credentials helper for Cloudsmith.

    Writes a ``terraform-credentials-cloudsmith`` launcher into Terraform's
    plugin directory and adds a ``credentials_helper "cloudsmith"`` block to
    ``~/.terraformrc``.

    Usage::

        installer = TerraformInstaller()
        actions = installer.install(helper_args=["--org", "acme"])
        for action in actions:
            print(action)
    """

    LAUNCHER_NAME = "terraform-credentials-cloudsmith"
    TARGET_CMD = "cloudsmith credential-helper terraform"

    name = "terraform"
    summary = "Terraform credentials helper for Cloudsmith registries"

    @classmethod
    def _resolve_target_cmd(cls) -> str:
        """Return the command the launcher forwards to.

        A pip/source install resolves the bare ``cloudsmith`` command via
        ``PATH``. A frozen standalone binary (PyInstaller) is not guaranteed to
        be on ``PATH`` under that name, so point the launcher at the absolute
        executable instead. The path is quoted so a directory containing spaces
        still execs correctly.
        """
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" credential-helper terraform'
        return cls.TARGET_CMD

    def _resolve_plugin_dir(self, bin_dir: str | None) -> Path:
        """Return the directory to install the launcher into.

        Defaults to Terraform's user plugin directory (Terraform ignores
        ``PATH`` for credentials helpers); an explicit *bin_dir* override is
        resolved to an absolute path.
        """
        if bin_dir is not None:
            return Path(bin_dir).resolve()
        return _default_plugin_dir()

    def _plugin_path(self, target_dir: Path) -> Path:
        """Return the launcher path within *target_dir* for this platform."""
        if os.name == "nt":
            return target_dir / f"{self.LAUNCHER_NAME}.cmd"
        return target_dir / self.LAUNCHER_NAME

    # ------------------------------------------------------------------
    # install / uninstall / status
    # ------------------------------------------------------------------

    def install(
        self,
        *,
        bin_dir: str | None = None,
        helper_args: tuple[str, ...] = (),
        dry_run: bool = False,
        # Accepted for a uniform installer interface; Terraform's helper is
        # host-agnostic (Terraform passes the hostname at call time).
        **kwargs,
    ) -> list[str]:
        """Install the Terraform credentials helper.

        Writes the launcher into Terraform's plugin directory and adds the
        ``credentials_helper "cloudsmith"`` block to ``~/.terraformrc``.

        Parameters
        ----------
        bin_dir:
            Override for the plugin directory to install the launcher into.
            Defaults to ``~/.terraform.d/plugins``.
        helper_args:
            Values for the block's ``args`` list, forwarded to the CLI on every
            invocation — e.g. ``("--org", "acme", "-P", "ci")`` to pin the
            organisation and profile without environment variables.
        dry_run:
            When ``True``, compute and return planned actions without writing.

        Returns
        -------
        list[str]
            Human-readable descriptions of actions taken (or planned).
        """
        target_dir = self._resolve_plugin_dir(bin_dir)
        launcher_path = self._plugin_path(target_dir)
        rc_path = _terraformrc_path()

        actions: list[str] = []

        existing = ""
        rc_exists = rc_path.exists()
        if rc_exists:
            existing = rc_path.read_text(encoding="utf-8")

        # Compute the terraformrc change up front so a conflict aborts before we
        # write the launcher — leaving no orphan behind.
        new_rc, rc_changed = terraformrc.add_or_update_block(
            existing, helper_args, rc_path=str(rc_path)
        )

        if dry_run:
            actions.append(f"would write launcher {launcher_path}")
            if rc_changed:
                verb = "add" if terraformrc.find_block(existing) is None else "update"
                actions.append(
                    f'would {verb} credentials_helper "cloudsmith" in {rc_path}'
                )
            else:
                actions.append(
                    f'credentials_helper "cloudsmith" already up to date'
                    f" in {rc_path} (no change)"
                )
            return actions

        # Real install: launcher first, then terraformrc.
        written = write_launcher(
            target_dir, self.LAUNCHER_NAME, self._resolve_target_cmd()
        )
        actions.append(f"wrote launcher {written}")

        if rc_changed:
            rc_path.parent.mkdir(parents=True, exist_ok=True)
            rc_path.write_text(new_rc, encoding="utf-8")
            verb = "added" if not rc_exists else "updated"
            actions.append(f'{verb} credentials_helper "cloudsmith" in {rc_path}')
        else:
            actions.append(f"{rc_path} already up to date")

        return actions

    def uninstall(
        self, *, bin_dir: str | None = None, dry_run: bool = False
    ) -> list[str]:
        """Uninstall the Terraform credentials helper.

        Removes the launcher and strips the ``credentials_helper "cloudsmith"``
        block from ``~/.terraformrc`` (a block for a different helper is left
        untouched).

        Parameters
        ----------
        bin_dir:
            Override for the plugin directory the launcher was installed into.
            Pass the same value given to :meth:`install`.
        dry_run:
            When ``True``, return planned actions without writing.

        Returns
        -------
        list[str]
            Human-readable descriptions of actions taken (or planned).
        """
        target_dir = self._resolve_plugin_dir(bin_dir)
        launcher_path = self._plugin_path(target_dir)
        rc_path = _terraformrc_path()

        actions: list[str] = []

        existing = ""
        rc_exists = rc_path.exists()
        if rc_exists:
            existing = rc_path.read_text(encoding="utf-8")
        new_rc, rc_changed = terraformrc.remove_block(existing)

        if dry_run:
            if launcher_path.exists():
                actions.append(f"would remove launcher {launcher_path}")
            else:
                actions.append(
                    f"launcher not found at {launcher_path} (nothing to remove)"
                )
            if rc_changed:
                actions.append(
                    f'would remove credentials_helper "cloudsmith" from {rc_path}'
                )
            else:
                actions.append(
                    f'no credentials_helper "cloudsmith" block to remove from {rc_path}'
                )
            return actions

        removed = remove_launcher(target_dir, self.LAUNCHER_NAME)
        if removed:
            actions.append(f"removed launcher {launcher_path}")
        else:
            actions.append(f"launcher not found at {launcher_path} (nothing to remove)")

        if rc_changed:
            rc_path.write_text(new_rc, encoding="utf-8")
            actions.append(f'removed credentials_helper "cloudsmith" from {rc_path}')
        else:
            actions.append(
                f'no credentials_helper "cloudsmith" block to remove from {rc_path}'
            )

        return actions

    def status(self) -> dict:
        """Return current installation status.

        Returns
        -------
        dict
            A dict with keys:

            ``"launcher"``
                The path of the launcher if it exists, else ``None``.
            ``"hosts"``
                A single marker when the ``credentials_helper "cloudsmith"``
                block is present in ``~/.terraformrc`` (the helper is
                host-agnostic — Terraform passes the hostname at call time), or
                an empty list.
        """
        target_dir = self._resolve_plugin_dir(None)
        launcher_path: Path | None = self._plugin_path(target_dir)
        if launcher_path is not None and not launcher_path.exists():
            launcher_path = None

        rc_path = _terraformrc_path()
        hosts: list[str] = []
        if rc_path.exists():
            try:
                text = rc_path.read_text(encoding="utf-8")
            except OSError:
                text = ""
            match = terraformrc.find_block(text)
            if match is not None and match.group("name") == terraformrc.HELPER_NAME:
                hosts.append("all Cloudsmith Terraform registries (credentials_helper)")

        return {
            "launcher": str(launcher_path) if launcher_path is not None else None,
            "hosts": hosts,
        }
