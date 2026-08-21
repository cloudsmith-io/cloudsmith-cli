"""CLI/Commands - Lazy command registry.

Maps each top-level command name to the module that registers it, and each
command to its aliases. The AliasGroup imports a module only when its
command runs, which keeps CLI startup fast. The tests in
``cli/tests/test_lazy_commands.py`` verify that this registry matches what
the modules declare.
"""

_PACKAGE = "cloudsmith_cli.cli.commands"

LAZY_COMMANDS = {
    "authenticate": f"{_PACKAGE}.auth",
    "check": f"{_PACKAGE}.check",
    "copy": f"{_PACKAGE}.copy",
    "credential-helper": f"{_PACKAGE}.credential_helper",
    "delete": f"{_PACKAGE}.delete",
    "dependencies": f"{_PACKAGE}.dependencies",
    "docs": f"{_PACKAGE}.docs",
    "domains": f"{_PACKAGE}.domains",
    "download": f"{_PACKAGE}.download",
    "entitlements": f"{_PACKAGE}.entitlements",
    "help": f"{_PACKAGE}.help_",
    "list": f"{_PACKAGE}.list_",
    "login": f"{_PACKAGE}.login",
    "logout": f"{_PACKAGE}.logout",
    "mcp": f"{_PACKAGE}.mcp",
    "metadata": f"{_PACKAGE}.metadata",
    "metrics": f"{_PACKAGE}.metrics",
    "move": f"{_PACKAGE}.move",
    "policy": f"{_PACKAGE}.policy",
    "push": f"{_PACKAGE}.push",
    "quarantine": f"{_PACKAGE}.quarantine",
    "quota": f"{_PACKAGE}.quota",
    "repositories": f"{_PACKAGE}.repos",
    "resync": f"{_PACKAGE}.resync",
    "status": f"{_PACKAGE}.status",
    "tags": f"{_PACKAGE}.tags",
    "tokens": f"{_PACKAGE}.tokens",
    "upstream": f"{_PACKAGE}.upstream",
    "vulnerabilities": f"{_PACKAGE}.vulnerabilities",
    "whoami": f"{_PACKAGE}.whoami",
}

LAZY_ALIASES = {
    "authenticate": ["auth"],
    "copy": ["cp"],
    "delete": ["rm"],
    "dependencies": ["deps"],
    "domains": ["domain"],
    "entitlements": ["ents"],
    "list": ["ls"],
    "login": ["token"],
    "move": ["mv", "promote"],
    "push": ["upload", "deploy"],
    "quarantine": ["block"],
    "repositories": ["repos"],
    "tags": ["tag"],
}
