# Copyright 2026 Cloudsmith Ltd
"""Installer for the Cargo credential provider.

Manages writing/removing the ``cargo-credential-cloudsmith`` launcher and
patching ``$CARGO_HOME/config.toml`` so Cargo routes registry authentication
through the Cloudsmith credential provider.

Cargo does not map credential providers to hostnames: a provider is registered
globally (``registry.global-credential-providers``) or per named registry
(``registries.<name>.credential-provider``), and is told the registry index URL
at call time.  Installing therefore registers the
provider globally — safe because the runtime answers ``url-not-supported`` for
anything that is not a Cloudsmith registry, so Cargo falls through to the next
provider — and additionally pins it on any already-configured registry whose
index points at a known Cloudsmith Cargo host.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import tomlkit

from ...core.cache_utils import merge_config_file
from ..backends import BackendKind
from ..common import extract_hostname
from ..custom_domains import get_format_domains
from ..launchers import is_on_path, remove_launcher, resolve_bin_dir, write_launcher

if TYPE_CHECKING:
    from ...core.credentials.models import CredentialResult

logger = logging.getLogger(__name__)


def _cargo_config_path() -> Path:
    """Return the path to the Cargo configuration file.

    Respects the ``CARGO_HOME`` environment variable; otherwise returns the
    platform default ``~/.cargo/config.toml``.  Note this is *not*
    ``credentials.toml``: credential providers are configured in
    ``config.toml``, while ``credentials.toml`` holds tokens (which this
    helper deliberately never writes — the token is resolved at call time).
    """
    cargo_home = os.environ.get("CARGO_HOME")
    base = Path(cargo_home) if cargo_home else Path.home() / ".cargo"
    return base / "config.toml"


class CargoInstaller:
    """Manages installation of the Cargo credential provider for Cloudsmith.

    This installer writes a ``cargo-credential-cloudsmith`` launcher binary and
    patches ``$CARGO_HOME/config.toml`` to register it as a credential
    provider.

    Usage::

        installer = CargoInstaller()
        actions = installer.install(domains=["my-registry.example.com"])
        for action in actions:
            print(action)
    """

    LAUNCHER_NAME = "cargo-credential-cloudsmith"
    TARGET_CMD = "cloudsmith credential-helper cargo"
    #: The value written into Cargo's config.  Cargo resolves a bare name
    #: through ``PATH`` (and requires the ``cargo-credential-`` prefix).
    PROVIDER_VALUE = "cargo-credential-cloudsmith"
    #: Cargo's built-in token provider.  Setting
    #: ``global-credential-providers`` replaces Cargo's default of
    #: ``["cargo:token"]``, so it has to be carried forward explicitly or
    #: hand-written tokens in ``credentials.toml`` stop working.
    TOKEN_PROVIDER = "cargo:token"
    DEFAULT_HOST = "cargo.cloudsmith.io"

    name = "cargo"
    summary = "Cargo credential provider for Cloudsmith registries"

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
            return f'"{sys.executable}" credential-helper cargo'
        return cls.TARGET_CMD

    # ------------------------------------------------------------------
    # config.toml mutation
    # ------------------------------------------------------------------

    def _add_provider(self, config: dict, hosts: list[str]) -> None:
        """Register the provider globally and on matching named registries."""
        registry = config.get("registry")
        if not isinstance(registry, dict):
            registry = config["registry"] = {}

        providers = registry.get("global-credential-providers")
        if isinstance(providers, list):
            providers = [p for p in providers if p != self.PROVIDER_VALUE]
        else:
            providers = [self.TOKEN_PROVIDER]

        # Cargo tries providers from last to first, so appending ours gives it
        # the highest precedence: it answers for Cloudsmith registries and
        # defers everything else back down the list.
        providers.append(self.PROVIDER_VALUE)
        registry["global-credential-providers"] = providers

        # A per-registry `credential-provider` shadows the global list, so pin
        # ours on any registry whose index is a known Cloudsmith Cargo host.
        for _name, entry in self._cloudsmith_registries(config, hosts):
            entry["credential-provider"] = self.PROVIDER_VALUE

    def _remove_provider(self, config: dict) -> None:
        """Strip every trace of this provider from a parsed config."""
        registry = config.get("registry")
        if isinstance(registry, dict):
            providers = registry.get("global-credential-providers")
            if isinstance(providers, list):
                remaining = [p for p in providers if p != self.PROVIDER_VALUE]
                if remaining != providers:
                    # A list of just the built-in token provider is exactly
                    # Cargo's default, so drop the key and let the default
                    # apply rather than leaving our edit behind.
                    if remaining in ([], [self.TOKEN_PROVIDER]):
                        del registry["global-credential-providers"]
                    else:
                        registry["global-credential-providers"] = remaining
            if not registry:
                del config["registry"]

        registries = config.get("registries")
        if isinstance(registries, dict):
            for entry in registries.values():
                if (
                    isinstance(entry, dict)
                    and entry.get("credential-provider") == self.PROVIDER_VALUE
                ):
                    del entry["credential-provider"]

    @staticmethod
    def _cloudsmith_registries(
        config: dict, hosts: list[str]
    ) -> list[tuple[str, dict]]:
        """Return ``(name, entry)`` for ``[registries.*]`` whose index is in *hosts*."""
        registries = config.get("registries")
        if not isinstance(registries, dict):
            return []

        wanted = {host.lower() for host in hosts}
        matches: list[tuple[str, dict]] = []
        for name, entry in registries.items():
            if not isinstance(entry, dict):
                continue
            index = entry.get("index")
            if isinstance(index, str) and extract_hostname(index) in wanted:
                matches.append((name, entry))
        return matches

    # ------------------------------------------------------------------
    # install / uninstall / status
    # ------------------------------------------------------------------

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
        """Install the Cargo credential provider.

        Writes the launcher binary and registers it in
        ``$CARGO_HOME/config.toml``.

        Parameters
        ----------
        bin_dir:
            Override for the directory to install the launcher.  Defaults to
            :func:`resolve_bin_dir` auto-detection.
        domains:
            Additional registry hostnames to recognise (in addition to the
            default ``cargo.cloudsmith.io``) when pinning the provider on
            named registries.
        discover:
            When ``True`` (default), attempt to auto-discover Cargo custom
            domains via the Cloudsmith API.  Discovery is best-effort and never
            prevents the provider from being registered.
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
        config_path = _cargo_config_path()

        actions: list[str] = []

        # Start with the default host plus any explicitly requested domains.
        hosts: list[str] = [self.DEFAULT_HOST, *domains]

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
                        BackendKind.CARGO,
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
                actions.append(
                    f"discovered {len(new_hosts)} new Cargo custom domain(s)"
                )
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

        # Recorded for the action log: which named registries get pinned.
        pinned: list[str] = []

        def mutate(config: dict) -> None:
            pinned.clear()
            pinned.extend(
                name for name, _ in self._cloudsmith_registries(config, hosts)
            )
            self._add_provider(config, hosts)

        if dry_run:
            if os.name == "nt":
                launcher_path = target_dir / f"{self.LAUNCHER_NAME}.cmd"
            else:
                launcher_path = target_dir / self.LAUNCHER_NAME
            actions.append(f"would write launcher {launcher_path}")

            would_change = merge_config_file(
                config_path, mutate, dry_run=True, format="toml"
            )
            if would_change:
                actions.append(
                    f"would add {self.PROVIDER_VALUE!r} to"
                    f" registry.global-credential-providers in {config_path}"
                )

                actions.extend(
                    [
                        (
                            f"would set registries.{name}.credential-provider"
                            f"={self.PROVIDER_VALUE!r} in {config_path}"
                        )
                        for name in pinned
                    ]
                )
            else:
                actions.append(
                    f"{self.PROVIDER_VALUE!r} already registered"
                    f" in {config_path} (no change)"
                )
            return actions

        # Real install
        launcher_path = write_launcher(
            target_dir, self.LAUNCHER_NAME, self._resolve_target_cmd()
        )
        actions.append(f"wrote launcher {launcher_path}")

        changed = merge_config_file(config_path, mutate, format="toml")
        if changed:
            actions.append(
                f"added {self.PROVIDER_VALUE!r} to"
                f" registry.global-credential-providers in {config_path}"
            )
            actions.extend(
                [
                    (
                        f"set registries.{name}.credential-provider"
                        f"={self.PROVIDER_VALUE!r} in {config_path}"
                    )
                    for name in pinned
                ]
            )
        else:
            actions.append(f"config.toml already up to date ({config_path})")

        if not is_on_path(target_dir):
            actions.append(
                f"WARNING: {target_dir} is not on PATH — "
                f"add it to your PATH so Cargo can find {self.LAUNCHER_NAME}"
            )

        return actions

    def uninstall(
        self, *, bin_dir: str | None = None, dry_run: bool = False
    ) -> list[str]:
        """Uninstall the Cargo credential provider.

        Removes the launcher binary and strips Cloudsmith-managed entries from
        ``$CARGO_HOME/config.toml``.

        Parameters
        ----------
        bin_dir:
            Override for the directory where the launcher was installed.
            Defaults to :func:`resolve_bin_dir` auto-detection.  Pass the same
            value that was given to :meth:`install` so the correct launcher file
            is found and removed.
        dry_run:
            When ``True``, return planned actions without writing any files.

        Returns
        -------
        list[str]
            Human-readable descriptions of actions taken (or planned).
        """
        target_dir = resolve_bin_dir(bin_dir)
        config_path = _cargo_config_path()

        actions: list[str] = []

        if os.name == "nt":
            launcher_path = target_dir / f"{self.LAUNCHER_NAME}.cmd"
        else:
            launcher_path = target_dir / self.LAUNCHER_NAME

        # An absent config is nothing to strip: merging into it would create an
        # empty config.toml as a parting gift.
        config_exists = config_path.exists()

        if dry_run:
            if launcher_path.exists():
                actions.append(f"would remove launcher {launcher_path}")
            else:
                actions.append(
                    f"launcher not found at {launcher_path} (nothing to remove)"
                )

            would_change = config_exists and merge_config_file(
                config_path, self._remove_provider, dry_run=True, format="toml"
            )
            if would_change:
                actions.append(
                    f"would remove {self.PROVIDER_VALUE!r} entries from {config_path}"
                )
            else:
                actions.append(
                    f"no {self.PROVIDER_VALUE!r} entries to remove from {config_path}"
                )
            return actions

        # Real uninstall
        removed = remove_launcher(target_dir, self.LAUNCHER_NAME)
        if removed:
            actions.append(f"removed launcher {launcher_path}")
        else:
            actions.append(f"launcher not found at {launcher_path} (nothing to remove)")

        changed = config_exists and merge_config_file(
            config_path, self._remove_provider, format="toml"
        )
        if changed:
            actions.append(
                f"removed {self.PROVIDER_VALUE!r} entries from {config_path}"
            )
        else:
            actions.append(
                f"no {self.PROVIDER_VALUE!r} entries to remove from {config_path}"
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
                Where the provider is registered in ``config.toml``: the index
                hostnames of named registries pinned to it, plus a marker when
                it is registered in ``registry.global-credential-providers``
                (which covers every registry, since Cargo passes the index URL
                at call time rather than matching on hostname).
        """
        target_dir = resolve_bin_dir()
        if os.name == "nt":
            launcher_path: Path | None = target_dir / f"{self.LAUNCHER_NAME}.cmd"
        else:
            launcher_path = target_dir / self.LAUNCHER_NAME

        if launcher_path is not None and not launcher_path.exists():
            launcher_path = None

        config_path = _cargo_config_path()
        hosts: list[str] = []
        if config_path.exists():
            try:
                data = tomlkit.loads(config_path.read_text(encoding="utf-8"))
            except (tomlkit.exceptions.ParseError, ValueError, OSError):
                data = {}

            registry = data.get("registry")
            if isinstance(registry, dict):
                providers = registry.get("global-credential-providers")
                if isinstance(providers, list) and self.PROVIDER_VALUE in providers:
                    hosts.append("all registries (global-credential-providers)")

            registries = data.get("registries")
            if isinstance(registries, dict):
                for entry in registries.values():
                    if (
                        not isinstance(entry, dict)
                        or entry.get("credential-provider") != self.PROVIDER_VALUE
                    ):
                        continue
                    index = entry.get("index")
                    host = extract_hostname(index) if isinstance(index, str) else ""
                    if host and host not in hosts:
                        hosts.append(host)

        return {
            "launcher": str(launcher_path) if launcher_path is not None else None,
            "hosts": hosts,
        }
