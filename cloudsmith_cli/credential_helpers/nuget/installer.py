# Copyright 2026 Cloudsmith Ltd
"""Installer for the NuGet credential provider.

Writes a ``nuget-plugin-cloudsmith`` launcher into a directory on ``PATH``.
NuGet 6.13+ (.NET SDK 9.0.200+, Visual Studio 17.13+) discovers any
executable named ``nuget-plugin-*`` on ``PATH`` as an authentication plugin,
so no NuGet configuration file changes.  On Windows NuGet only discovers
``.exe`` and ``.bat`` files, so the launcher is a ``.bat``.
"""

from __future__ import annotations

from ..common import path_warning
from ..launchers import (
    helper_command,
    is_on_path,
    is_windows,
    launcher_arg,
    launcher_filename,
    remove_launcher,
    resolve_bin_dir,
    write_launcher,
)


class NuGetInstaller:
    """Manages installation of the NuGet credential provider for Cloudsmith."""

    LAUNCHER_NAME = "nuget-plugin-cloudsmith"
    WINDOWS_SUFFIX = ".bat"
    # NuGet can run the plugin from an IDE or a build agent without the
    # install's environment, so the launcher keeps the install-time settings.
    KEEPS_INSTALL_TIME_SETTINGS = True

    name = "nuget"
    summary = "NuGet credential provider for Cloudsmith feeds"

    @classmethod
    def _resolve_target_cmd(cls, domains: tuple[str, ...], discover: bool) -> str:
        """Return the command the launcher forwards to.

        ``--`` stops the CLI from parsing NuGet's ``-Plugin`` argument as its
        own option.
        """
        args = [f"--domain {launcher_arg('--domain', domain)}" for domain in domains]
        if not discover:
            args.append("--no-discover")
        return " ".join([helper_command(cls.name), *args, "--"])

    def _launcher_path(self, target_dir):
        return target_dir / launcher_filename(
            self.LAUNCHER_NAME, windows=is_windows(), windows_suffix=self.WINDOWS_SUFFIX
        )

    def install(
        self,
        *,
        bin_dir: str | None = None,
        domains: tuple[str, ...] = (),
        discover: bool = True,
        launcher_env: dict[str, str] | None = None,
        dry_run: bool = False,
        # Accepted for a uniform installer interface.
        **kwargs,
    ) -> list[str]:
        """Install the NuGet credential provider.

        Parameters
        ----------
        bin_dir:
            Override for the directory to install the launcher.  It must be on
            ``PATH`` for NuGet to discover the plugin.
        domains:
            Feed hosts that the plugin always authenticates.  NuGet sends
            every feed to the plugin, so the launcher passes them to it.
        discover:
            When ``False``, the plugin does not look up the Workspace's NuGet
            domains through the Cloudsmith API.
        launcher_env:
            ``CLOUDSMITH_*`` settings that the launcher sets, from
            :func:`~cloudsmith_cli.credential_helpers.launchers.install_time_settings`.
        dry_run:
            When ``True``, return planned actions without writing any files.

        Returns
        -------
        list[str]
            Human-readable descriptions of actions taken (or planned).
        """
        target_dir = resolve_bin_dir(bin_dir)
        launcher_path = write_launcher(
            target_dir,
            self.LAUNCHER_NAME,
            self._resolve_target_cmd(domains, discover),
            dry_run=dry_run,
            windows_suffix=self.WINDOWS_SUFFIX,
            env=launcher_env,
        )
        actions = [
            (
                f"would write launcher {launcher_path}"
                if dry_run
                else f"wrote launcher {launcher_path}"
            )
        ]
        if launcher_env:
            actions.append(f"launcher sets {', '.join(launcher_env)}")

        if not is_on_path(target_dir):
            actions.append(
                path_warning(target_dir, "NuGet", self.LAUNCHER_NAME, is_windows())
            )

        return actions

    def uninstall(
        self, *, bin_dir: str | None = None, dry_run: bool = False
    ) -> list[str]:
        """Remove the NuGet credential provider launcher."""
        target_dir = resolve_bin_dir(bin_dir)
        launcher_path = self._launcher_path(target_dir)

        removed = remove_launcher(
            target_dir,
            self.LAUNCHER_NAME,
            dry_run=dry_run,
            windows_suffix=self.WINDOWS_SUFFIX,
        )
        if not removed:
            return [f"launcher not found at {launcher_path} (nothing to remove)"]
        if dry_run:
            return [f"would remove launcher {launcher_path}"]
        return [f"removed launcher {launcher_path}"]

    def status(self) -> dict:
        """Return current installation status.

        The plugin is host-agnostic: NuGet sends it every feed URL, so
        ``hosts`` is a single marker when the launcher exists.
        """
        launcher_path = self._launcher_path(resolve_bin_dir())
        if not launcher_path.exists():
            return {"launcher": None, "hosts": []}
        return {
            "launcher": str(launcher_path),
            "hosts": ["all Cloudsmith NuGet feeds (nuget-plugin)"],
        }
