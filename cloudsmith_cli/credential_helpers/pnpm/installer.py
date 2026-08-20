# Copyright 2026 Cloudsmith Ltd
import logging
import os
import sys
from pathlib import Path

from cloudsmith_cli.credential_helpers.backends import BackendKind
from cloudsmith_cli.credential_helpers.custom_domains import get_format_domains
from cloudsmith_cli.credential_helpers.generic import PartialInstallError
from cloudsmith_cli.credential_helpers.launchers import (
    remove_launcher,
    resolve_bin_dir,
    write_launcher,
)
from cloudsmith_cli.credential_helpers.pnpm.rc import NPMRC, AuthKeyConflictError

from ...core.credentials.models import CredentialResult

logger = logging.getLogger(__name__)


def _config_path() -> Path:
    npm_user_config = os.environ.get("NPM_CONFIG_USERCONFIG")

    if npm_user_config:
        return Path(npm_user_config)

    return Path.home() / ".npmrc"


class PNPMInstaller:
    LAUNCHER_NAME = "pnpm-credential-cloudsmith"
    TARGET_CMD = "cloudsmith credential-helper pnpm"
    DEFAULT_HOST = "npm.cloudsmith.io"

    name = "pnpm"
    summary = "pnpm credential helper for Cloudsmith registries"

    @classmethod
    def _resolve_target_cmd(cls) -> str:
        """Return the command the launcher forwards to.

        A pip/source install resolves the bare ``cloudsmith`` command via
        ``PATH``.  A frozen standalone binary (PyInstaller) is not guaranteed
        to be on ``PATH`` under that name, so point the launcher at the
        absolute executable instead — mirroring the frozen handling in
        :func:`cloudsmith_cli.cli.commands.mcp._get_server_config`.  The path
        is quoted so a directory containing spaces still execs correctly.
        """
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" credential-helper pnpm'
        return cls.TARGET_CMD

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
        """Install the pnpm credential helper.

        Writes the launcher binary and registers Cloudsmith registry hosts in
        ``${NPM_CONFIG_USERCONFIG:-~/.npmrc}``.

        Parameters
        ----------
        bin_dir:
            Override for the directory to install the launcher.  Defaults to
            :func:`resolve_bin_dir` auto-detection.
        domains:
            Additional registry hostnames to configure (in addition to the
            default ``npm.cloudsmith.io``).
        discover:
            When ``True`` (default), attempt to auto-discover pnpm custom
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
        config_path = _config_path()

        actions: list[str] = []

        # Start with the default host plus any explicitly requested domains.
        hosts: list[str] = [self.DEFAULT_HOST, *domains]

        if discover:
            if dry_run:
                actions.append("skipped custom-domain auto-discovery (dry run)")
            elif org and credential and credential.api_key:
                try:
                    discovered = get_format_domains(
                        org,
                        BackendKind.NPM,
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
                new_hosts = [h for h in discovered if h not in hosts]
                hosts.extend(discovered)
                actions.append(f"discovered {len(new_hosts)} new pnpm custom domain(s)")
            else:
                logger.debug(
                    "skipped auto-discovery"
                    " (no organization/credentials; pass --no-discover to silence)"
                )

        # De-duplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for h in hosts:
            if h not in seen:
                seen.add(h)
                deduped.append(h)
        hosts = deduped

        # Real install
        launcher_path = write_launcher(
            target_dir, self.LAUNCHER_NAME, self._resolve_target_cmd(), dry_run=dry_run
        )
        if dry_run:
            actions.append(f"would write launcher {launcher_path}")
        else:
            actions.append(f"wrote launcher {launcher_path}")

        with NPMRC(config_path, modifiable=not dry_run) as rc:
            for host in hosts:
                entry = NPMRC.URLEntry.from_values(
                    host, "tokenHelper", str(launcher_path)
                )
                try:
                    added = rc.add(entry)
                except AuthKeyConflictError as e:
                    if dry_run:
                        actions.append(
                            f"WARNING would not set {entry} in {config_path} as {e} already set"
                        )
                    else:
                        actions.append(
                            f"WARNING did not set {entry} in {config_path} as {e} already set"
                        )
                    continue

                if dry_run:
                    if added:
                        actions.append(f"would set {entry} in {config_path}")
                    else:
                        actions.append(
                            f"{entry} already set in {config_path} (no change)"
                        )

            if rc.failures > 0:
                raise PartialInstallError(actions)
            elif not rc.modified:
                actions.append(f"npmrc already up to date ({config_path})")

        return actions

    def uninstall(
        self, *, bin_dir: str | None = None, dry_run: bool = False
    ) -> list[str]:
        config_path = _config_path()
        actions: list[str] = []

        target_dir = resolve_bin_dir(bin_dir)

        if not config_path.exists():
            actions.append(".npmrc file doesn't exist, nothing to do")
            return actions

        if os.name == "nt":
            launcher_path = target_dir / f"{self.LAUNCHER_NAME}.cmd"
        else:
            launcher_path = target_dir / self.LAUNCHER_NAME

        with NPMRC(config_path, modifiable=not dry_run) as rc:
            hosts: list[str] = rc.helped_hosts(str(launcher_path))
            for host in hosts:
                removed = rc.remove(NPMRC.URLEntry.from_values(host, "tokenHelper"))
                if dry_run:
                    if removed:
                        actions.append(
                            f"would remove //{host}/:tokenHelper from {config_path}"
                        )
                    else:
                        actions.append(f"domain {host} not installed in {config_path}")

        removed = remove_launcher(target_dir, self.LAUNCHER_NAME, dry_run=dry_run)
        if removed:
            if dry_run:
                actions.append(f"would remove launcher {launcher_path}")
            else:
                actions.append(f"removed launcher {launcher_path}")
        else:
            actions.append(f"launcher not found at {launcher_path} (nothing to remove)")

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

        config_path = _config_path()

        hosts: list[str] = []
        if config_path.exists():
            with NPMRC(config_path) as rc:
                hosts: list[str] = rc.helped_hosts(str(launcher_path))

        return {
            "launcher": str(launcher_path) if launcher_path is not None else None,
            "hosts": hosts,
        }
