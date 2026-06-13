# Copyright 2026 Cloudsmith Ltd
"""Plugin protocol and registry for shell-plugin credential helpers.

A *plugin* knows how to provision ephemeral credentials for one package
manager that lacks a native credential helper (e.g. Maven).  The runner looks
a plugin up by the command being run (its binary name) and asks it to
provision per-invocation config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .config import PluginEntry


@dataclass
class ProvisionResult:
    """The per-invocation provisioning a plugin produces for one command.

    ``env`` are extra environment variables to set on the child process,
    ``prepend_args`` are inserted before the user's arguments, and
    ``temp_dirs`` are removed after the child exits.
    """

    env: dict[str, str] = field(default_factory=dict)
    prepend_args: list[str] = field(default_factory=list)
    temp_dirs: list[str] = field(default_factory=list)


class Plugin(Protocol):
    """A package-manager shell plugin."""

    name: str
    binary_name: str

    def skip_auth_args(self) -> list[str]:
        """Args that mean 'no credentials needed' (e.g. ``--version``)."""

    def provision(
        self, entry: PluginEntry, token: str, args: list[str]
    ) -> ProvisionResult:
        """Write ephemeral credentials and return how to run the binary."""


def _registry() -> dict[str, Plugin]:
    """Build the plugin registry (imported lazily to avoid import cycles)."""
    from .maven import MavenPlugin

    return {"maven": MavenPlugin()}


def get(name: str) -> Plugin | None:
    """Return the registered plugin for *name*, or ``None``."""
    return _registry().get(name)


def get_by_binary(binary_name: str) -> Plugin | None:
    """Return the plugin whose ``binary_name`` matches, or ``None``."""
    for plugin in _registry().values():
        if plugin.binary_name == binary_name:
            return plugin
    return None


def names() -> list[str]:
    """Return the sorted names of registered plugins."""
    return sorted(_registry())
