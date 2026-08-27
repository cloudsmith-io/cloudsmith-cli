# Copyright 2026 Cloudsmith Ltd
"""Tests for the Workspace option and its accepted spellings.

``--workspace`` and ``-w`` use current Cloudsmith terminology. ``--org``,
``--organization``, ``--oidc-org``, ``--owner``, and ``-o`` remain available
for compatibility. All seven flags are one option.
"""

import click
import click.testing
import pytest

from ..config import OPTIONS, ConfigReader, Options
from ..decorators import resolve_credentials


@pytest.fixture
def config_file(tmp_path):
    """Yield a writer for a temporary config.ini, restoring reader state."""
    original_files = list(ConfigReader.config_files)

    def write(body):
        path = tmp_path / "config.ini"
        path.write_text(body)
        return str(path)

    yield write
    ConfigReader.config_files = original_files


@pytest.fixture
def org_reporting_command(monkeypatch):
    """A minimal command carrying the shared credential options.

    The Options object is a process-wide thread-local, so it is cleared per
    test to stop one invocation's organisation leaking into the next.
    """
    monkeypatch.delenv("CLOUDSMITH_WORKSPACE", raising=False)
    monkeypatch.delenv("CLOUDSMITH_ORG", raising=False)
    monkeypatch.delattr(OPTIONS, "value", raising=False)

    @click.command()
    @resolve_credentials
    @click.pass_context
    def report(ctx, opts):  # pylint: disable=unused-argument
        click.echo(f"org={opts.org}")

    return report


@pytest.mark.parametrize("key", ["workspace", "org", "organization", "oidc_org"])
def test_every_config_spelling_sets_the_one_organisation(config_file, key):
    """The aliases are one value in config.ini, not three independent settings."""
    opts = Options()
    opts.load_config_file(config_file(f"[default]\n{key} = acme\n"))

    assert opts.org == "acme"
    assert opts.workspace == "acme"
    assert opts.organization == "acme"
    assert opts.oidc_org == "acme"


def test_workspace_config_takes_precedence_over_legacy_aliases(config_file):
    """The current config key wins regardless of the order used in the file."""
    opts = Options()
    opts.load_config_file(
        config_file(
            "[default]\n"
            "workspace = preferred-workspace\n"
            "org = legacy-org\n"
            "organization = legacy-organization\n"
            "oidc_org = legacy-oidc-org\n"
        )
    )

    assert opts.workspace == "preferred-workspace"
    assert opts.org == "preferred-workspace"


@pytest.mark.parametrize("empty_workspace", ["", '""', "''", '"   "'])
def test_empty_workspace_config_does_not_mask_legacy_alias(
    config_file, empty_workspace
):
    """An empty preferred key allows a populated compatibility key to apply."""
    opts = Options()
    opts.load_config_file(
        config_file(
            f"[default]\nworkspace = {empty_workspace}\norg = legacy-workspace\n"
        )
    )

    assert opts.workspace == "legacy-workspace"


@pytest.mark.parametrize(
    "flag",
    [
        "--workspace",
        "-w",
        "--org",
        "--organization",
        "--oidc-org",
        "--owner",
        "-o",
    ],
)
def test_every_flag_sets_the_organisation(org_reporting_command, flag):
    """Every flag reaches the existing internal ``opts.org`` value."""
    result = click.testing.CliRunner().invoke(org_reporting_command, [flag, "acme"])

    assert result.exit_code == 0, result.output
    assert "org=acme" in result.output


@pytest.mark.parametrize("envvar", ["CLOUDSMITH_WORKSPACE", "CLOUDSMITH_ORG"])
def test_environment_sets_the_organisation(org_reporting_command, monkeypatch, envvar):
    """Both environment-variable spellings set the internal organisation value."""
    monkeypatch.setenv(envvar, "acme-from-env")

    result = click.testing.CliRunner().invoke(org_reporting_command, [])

    assert result.exit_code == 0, result.output
    assert "org=acme-from-env" in result.output


def test_workspace_environment_takes_precedence(org_reporting_command, monkeypatch):
    """Current Workspace terminology wins when both environment aliases are set."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "legacy-org")
    monkeypatch.setenv("CLOUDSMITH_WORKSPACE", "preferred-workspace")

    result = click.testing.CliRunner().invoke(org_reporting_command, [])

    assert result.exit_code == 0, result.output
    assert "org=preferred-workspace" in result.output
