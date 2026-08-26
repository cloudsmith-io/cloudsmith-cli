# Copyright 2026 Cloudsmith Ltd
"""Tests for the Workspace option and its accepted spellings.

``--workspace`` and ``-w`` use current Cloudsmith terminology. ``--org``,
``--organization``, and ``--oidc-org`` remain available for compatibility.
All five flags are one option.
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
    monkeypatch.delenv("CLOUDSMITH_ORG", raising=False)
    monkeypatch.delattr(OPTIONS, "value", raising=False)

    @click.command()
    @resolve_credentials
    @click.pass_context
    def report(ctx, opts):  # pylint: disable=unused-argument
        click.echo(f"org={opts.org}")

    return report


@pytest.mark.parametrize("key", ["org", "organization", "oidc_org"])
def test_every_config_spelling_sets_the_one_organisation(config_file, key):
    """The aliases are one value in config.ini, not three independent settings."""
    opts = Options()
    opts.load_config_file(config_file(f"[default]\n{key} = acme\n"))

    assert opts.org == "acme"
    assert opts.organization == "acme"
    assert opts.oidc_org == "acme"


@pytest.mark.parametrize(
    "flag", ["--workspace", "-w", "--org", "--organization", "--oidc-org"]
)
def test_every_flag_sets_the_organisation(org_reporting_command, flag):
    """Every flag reaches the existing internal ``opts.org`` value."""
    result = click.testing.CliRunner().invoke(org_reporting_command, [flag, "acme"])

    assert result.exit_code == 0, result.output
    assert "org=acme" in result.output


def test_environment_sets_the_organisation(org_reporting_command, monkeypatch):
    """CLOUDSMITH_ORG is unchanged by the rename, and is still honoured."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme-from-env")

    result = click.testing.CliRunner().invoke(org_reporting_command, [])

    assert result.exit_code == 0, result.output
    assert "org=acme-from-env" in result.output
