# Copyright 2026 Cloudsmith Ltd
"""Installer for the NuGet credential provider.

Writes a ``nuget-plugin-cloudsmith`` launcher into a directory on ``PATH``.
NuGet 6.13+ (.NET SDK 9.0.200+, Visual Studio 17.13+) discovers any
executable named ``nuget-plugin-*`` on ``PATH`` as a cross-platform
authentication plugin, so no NuGet configuration file is modified.  On
Windows NuGet only considers ``.exe`` and ``.bat`` files, so the launcher is
written as a ``.bat``.
"""

from __future__ import annotations

import itertools
import logging
import re
import shlex
from typing import TYPE_CHECKING

from ..backends import BackendKind
from ..custom_domains import get_cache_path, get_format_domains, read_cache
from ..default_domains import default_hosts
from ..launchers import (
    _is_windows,
    _launcher_filename,
    credential_helper_command,
    is_on_path,
    remove_launcher,
    resolve_bin_dir,
    write_launcher,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ...core.credentials.models import CredentialResult

logger = logging.getLogger(__name__)

# Workspace slugs and hostnames are baked into a shell/batch script, so only
# characters that need no quoting on either platform are accepted.
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class NuGetInstallError(ValueError):
    """Raised when an install argument cannot be baked into the launcher."""


def _validate_token(kind: str, value: str) -> str:
    if not _SAFE_TOKEN.fullmatch(value):
        raise NuGetInstallError(
            f"Invalid {kind} {value!r}: only letters, digits, '.', '_' and '-' "
            "are allowed."
        )
    return value


class NuGetInstaller:
    """Manages installation of the NuGet credential provider for Cloudsmith."""

    LAUNCHER_NAME = "nuget-plugin-cloudsmith"
    WINDOWS_SUFFIX = ".bat"

    name = "nuget"
    summary = "NuGet credential provider for Cloudsmith feeds"

    @classmethod
    def _launcher_command(cls, workspace: str | None, domains: list[str]) -> str:
        """Return the launcher's target command with install-time args baked in.

        NuGet starts the plugin from IDEs and build servers whose environment
        may lack ``CLOUDSMITH_WORKSPACE``, so the Workspace used for
        custom-domain matching is pinned here.  ``--`` stops the CLI from
        parsing NuGet's own ``-Plugin`` switch as its options.
        """
        args: list[str] = []
        if workspace:
            args.extend(["--workspace", workspace])
        for domain in domains:
            args.extend(["--domain", domain])
        args.append("--")
        return " ".join([credential_helper_command(cls.name), *args])

    @classmethod
    def _launcher_path(cls, target_dir: Path) -> Path:
        return target_dir / _launcher_filename(
            cls.LAUNCHER_NAME,
            windows=_is_windows(),
            windows_suffix=cls.WINDOWS_SUFFIX,
        )

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
        dry_run: bool = False,
    ) -> list[str]:
        """Install the NuGet credential provider.

        Parameters
        ----------
        bin_dir:
            Override for the directory to install the launcher.  It must be on
            ``PATH`` for NuGet to discover the plugin.
        domains:
            Additional feed hostnames the provider should answer for, baked
            into the launcher.  Use this for a custom domain when discovery is
            unavailable.
        discover:
            When ``True`` (default), discover the Workspace's NuGet custom
            domains via the Cloudsmith API.  This also warms the custom-domain
            cache, so NuGet's first request does not wait on the API.
        refresh:
            When ``True``, bypass the domain cache during discovery.
        org:
            Workspace slug used for custom-domain discovery; baked into the
            launcher so the provider matches the same custom domains at
            runtime.
        credential:
            Resolved credential used for custom-domain discovery.
        api_host:
            Cloudsmith API host URL override.
        dry_run:
            When ``True``, compute and return planned actions without writing
            any files.

        Returns
        -------
        list[str]
            Human-readable descriptions of actions taken (or planned).
        """
        if org:
            _validate_token("workspace", org)
        extra_domains: list[str] = []
        for domain in domains:
            domain = _validate_token("domain", domain.strip().lower())
            if domain not in extra_domains:
                extra_domains.append(domain)

        target_dir = resolve_bin_dir(bin_dir)
        actions: list[str] = []

        if discover:
            if dry_run:
                actions.append("skipped custom-domain auto-discovery (dry run)")
            elif org and credential and credential.api_key:
                from ...core.api.exceptions import ApiException

                # A strict lookup reports a failure instead of reading it as
                # "no custom domains"; discovery still never aborts the install.
                try:
                    discovered = get_format_domains(
                        org,
                        BackendKind.NUGET,
                        credential=credential,
                        api_host=api_host,
                        refresh=refresh,
                        strict=True,
                    )
                except ApiException as exc:
                    actions.append(
                        f"WARNING: custom-domain auto-discovery failed: {exc}"
                    )
                    discovered = []
                summary = f"discovered {len(discovered)} NuGet custom domain(s)"
                if discovered:
                    summary += f": {', '.join(discovered)}"
                actions.append(summary)
            else:
                logger.debug(
                    "skipped auto-discovery"
                    " (no workspace/credentials; pass --no-discover to silence)"
                )

        launcher_path = write_launcher(
            target_dir,
            self.LAUNCHER_NAME,
            self._launcher_command(org, extra_domains),
            dry_run=dry_run,
            windows_suffix=self.WINDOWS_SUFFIX,
        )
        if dry_run:
            actions.append(f"would write launcher {launcher_path}")
        else:
            actions.append(f"wrote launcher {launcher_path}")

        if not is_on_path(target_dir):
            actions.append(
                f"WARNING: {target_dir} is not on PATH — add it to your PATH so "
                f"NuGet can discover {self.LAUNCHER_NAME} (requires NuGet 6.13+ / "
                ".NET SDK 9.0.200+)"
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

    @staticmethod
    def _baked_args(launcher_path: Path) -> tuple[str | None, list[str]]:
        """Return the Workspace and ``--domain`` hosts baked into a launcher."""
        try:
            text = launcher_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None, []
        try:
            tokens = shlex.split(text, posix=not _is_windows())
        except ValueError:
            tokens = text.split()
        workspace = None
        domains: list[str] = []
        for flag, value in itertools.pairwise(tokens):
            if flag == "--workspace":
                workspace = value
            elif flag == "--domain":
                domains.append(value)
        return workspace, domains

    def status(self) -> dict:
        """Return current installation status.

        ``hosts`` lists the default NuGet hosts, any ``--domain`` hosts
        baked into the launcher, and the NuGet custom domains already in the
        local cache for the baked Workspace (no API call is made).
        """
        launcher_path = self._launcher_path(resolve_bin_dir())
        if not launcher_path.exists():
            return {"launcher": None, "hosts": []}

        workspace, hosts = self._baked_args(launcher_path)
        hosts = [*default_hosts(BackendKind.NUGET), *hosts]
        if workspace:
            for domain in read_cache(get_cache_path(workspace)) or []:
                if (
                    domain.backend_kind == int(BackendKind.NUGET)
                    and domain.is_active
                    and domain.host not in hosts
                ):
                    hosts.append(domain.host)

        return {"launcher": str(launcher_path), "hosts": hosts}
