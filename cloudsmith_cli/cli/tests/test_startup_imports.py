"""Tests that a CLI import does not load heavy dependencies.

The credential helpers run the CLI on every package-manager request, so
module-level imports are the dominant startup cost. These tests import the
CLI in a subprocess and inspect ``sys.modules``.
"""

import json
import subprocess
import sys

HEAVY_PREFIXES = ("mcp", "httpx", "cloudsmith_api", "requests")


def modules_loaded_by_cli_import():
    code = (
        "import json, sys\n"
        "import cloudsmith_cli.cli.commands.main\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_cli_import_does_not_load_heavy_modules():
    modules = modules_loaded_by_cli_import()
    heavy = [
        name
        for name in modules
        if any(name == p or name.startswith(p + ".") for p in HEAVY_PREFIXES)
    ]
    assert heavy == []


def test_cli_import_does_not_load_command_modules():
    package = "cloudsmith_cli.cli.commands."
    allowed = {package + "main", package + "registry"}
    loaded = [
        name
        for name in modules_loaded_by_cli_import()
        if name.startswith(package) and name not in allowed
    ]
    assert loaded == []
