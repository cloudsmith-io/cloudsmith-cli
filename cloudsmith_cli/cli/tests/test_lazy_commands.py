"""Tests that the lazy command registry matches the command modules.

The registry duplicates the command names and aliases that the modules
declare, so the CLI can resolve a command without importing every module.
These tests import every command module and compare the result with the
registry to catch drift.
"""

import importlib
import pkgutil

from cloudsmith_cli.cli import commands
from cloudsmith_cli.cli.commands.main import main
from cloudsmith_cli.cli.commands.registry import LAZY_ALIASES, LAZY_COMMANDS


def import_every_command_module():
    prefix = commands.__name__ + "."
    for module_info in pkgutil.walk_packages(commands.__path__, prefix=prefix):
        importlib.import_module(module_info.name)


def test_registry_matches_registered_commands():
    import_every_command_module()
    assert set(main.commands) == set(LAZY_COMMANDS)


def test_registry_matches_registered_aliases():
    import_every_command_module()
    assert {name: list(aliases) for name, aliases in main.aliases.items()} == (
        LAZY_ALIASES
    )


def test_every_command_and_alias_resolves():
    ctx = main.make_context("cloudsmith", [], resilient_parsing=True)
    for name in list(LAZY_COMMANDS) + [a for al in LAZY_ALIASES.values() for a in al]:
        assert main.get_command(ctx, name) is not None, name
