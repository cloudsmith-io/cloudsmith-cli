"""Tests that a CLI import does not load heavy dependencies.

The credential helpers run the CLI on every package-manager request, so
module-level imports are the dominant startup cost. These tests import the
CLI in a subprocess and inspect ``sys.modules``.
"""

import json
import subprocess
import sys

HEAVY_PREFIXES = (
    "mcp",
    "httpx",
    "cloudsmith_api",
    "requests",
    "rich",
    "urllib3",
    "semver",
)


def modules_loaded_by_import(module_name="cloudsmith_cli.cli.commands.main"):
    code = (
        "import json, sys\n"
        f"import {module_name}\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def heavy_modules_in(modules):
    return [
        name
        for name in modules
        if any(name == p or name.startswith(p + ".") for p in HEAVY_PREFIXES)
    ]


def test_cli_import_does_not_load_heavy_modules():
    assert heavy_modules_in(modules_loaded_by_import()) == []


def test_cli_import_does_not_load_command_modules():
    package = "cloudsmith_cli.cli.commands."
    allowed = {package + "main", package + "registry"}
    loaded = [
        name
        for name in modules_loaded_by_import()
        if name.startswith(package) and name not in allowed
    ]
    assert loaded == []


def test_docker_helper_import_does_not_load_heavy_modules():
    modules = modules_loaded_by_import("cloudsmith_cli.credential_helpers.docker")
    assert heavy_modules_in(modules) == []


def test_terraform_helper_import_does_not_load_heavy_modules():
    modules = modules_loaded_by_import("cloudsmith_cli.credential_helpers.terraform")
    assert heavy_modules_in(modules) == []
