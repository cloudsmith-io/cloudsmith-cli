"""Registered-command tests for ``cloudsmith push skills --changelog``."""

from unittest.mock import patch

import pytest

from .. import config as cli_config
from ..commands.main import main

_MOCK_TARGETS = (
    "cloudsmith_cli.cli.commands.push.validate_create_package",
    "cloudsmith_cli.cli.commands.push.validate_upload_file",
    "cloudsmith_cli.cli.commands.push.upload_file",
    "cloudsmith_cli.cli.commands.push.create_package",
    "cloudsmith_cli.cli.commands.push.wait_for_package_sync",
)


@pytest.fixture(autouse=True)
def hermetic_environment(monkeypatch):
    """Keep developer environment and config values out of command tests."""
    monkeypatch.delenv("CLOUDSMITH_ORG", raising=False)
    monkeypatch.delenv("CLOUDSMITH_CONFIG_FILE", raising=False)
    monkeypatch.delattr(cli_config.OPTIONS, "value", raising=False)
    monkeypatch.setattr(cli_config.ConfigReader, "config_files", ["config.ini"])
    monkeypatch.setattr(cli_config.ConfigReader, "config_searchpath", ["."])


def test_changelog_is_sent_to_the_api(runner, tmp_path):
    package_file = tmp_path / "my-skill.zip"
    package_file.write_bytes(b"dummy content")

    with (
        patch(_MOCK_TARGETS[0]) as mock_validate_create_package,
        patch(_MOCK_TARGETS[1], return_value="checksum"),
        patch(_MOCK_TARGETS[2], return_value="uploaded:my-skill.zip"),
        patch(
            _MOCK_TARGETS[3], return_value=("slug-perm", "slug")
        ) as mock_create_package,
        patch(_MOCK_TARGETS[4]),
    ):
        result = runner.invoke(
            main,
            [
                "push",
                "skills",
                "example/repo",
                str(package_file),
                "--name",
                "my-skill",
                "--version",
                "1.0.0",
                "--changelog",
                "Fixed a bug",
                "--api-key",
                "fake-api-key",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output

    # Validation runs before file upload -> check kwargs passed through
    validation_kwargs = mock_validate_create_package.call_args.kwargs
    assert validation_kwargs["changelog"] == "Fixed a bug"

    # The create call persists the package -> check kwargs gets sent to package creation
    create_kwargs = mock_create_package.call_args.kwargs
    assert create_kwargs["changelog"] == "Fixed a bug"


def test_push_skills_help_documents_changelog_option(runner):
    result = runner.invoke(main, ["push", "skills", "--help"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "--changelog" in result.output


def test_push_non_skills_format_has_no_changelog_option(runner):
    result = runner.invoke(main, ["push", "raw", "--help"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "--changelog" not in result.output
