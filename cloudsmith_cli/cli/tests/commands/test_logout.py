import json
import os
from unittest.mock import patch

import click.testing
import pytest

from ...commands.logout import logout

HOST = "https://api.example.com"
CREDS_PATH = "/home/user/.config/cloudsmith/credentials.ini"


@pytest.fixture()
def runner():
    return click.testing.CliRunner()


@pytest.fixture
def mock_no_keyring_env():
    """Ensure CLOUDSMITH_NO_KEYRING and CLOUDSMITH_API_KEY are not set."""
    env = os.environ.copy()
    env.pop("CLOUDSMITH_NO_KEYRING", None)
    env.pop("CLOUDSMITH_API_KEY", None)
    with patch.dict(os.environ, env, clear=True):
        yield


@pytest.fixture
def mock_deps(mock_no_keyring_env):
    """Patch keyring and CredentialsReader with sensible defaults."""
    with (
        patch("cloudsmith_cli.cli.commands.logout.keyring") as mk,
        patch("cloudsmith_cli.cli.commands.logout.CredentialsReader") as mc,
    ):
        mc.find_existing_files.return_value = [CREDS_PATH]
        mk.should_use_keyring.return_value = True
        mk.has_sso_tokens.return_value = True
        yield mc, mk


class TestLogoutCommand:
    """Tests for the cloudsmith logout command."""

    def test_full_logout(self, runner, mock_deps):
        mock_creds, mock_keyring = mock_deps

        result = runner.invoke(logout, ["--api-host", HOST])

        assert result.exit_code == 0
        mock_creds.clear_api_key.assert_called_once_with(CREDS_PATH)
        mock_keyring.delete_sso_tokens.assert_called_once_with(HOST)
        assert "Removed credentials from:" in result.output
        assert "Removed SSO tokens from system keyring" in result.output

    def test_dry_run(self, runner, mock_deps):
        mock_creds, mock_keyring = mock_deps

        result = runner.invoke(logout, ["--dry-run", "--api-host", HOST])

        assert result.exit_code == 0
        mock_creds.clear_api_key.assert_not_called()
        mock_keyring.delete_sso_tokens.assert_not_called()
        assert "Would remove" in result.output

    def test_keyring_only_and_config_only_are_mutually_exclusive(self, runner):
        result = runner.invoke(
            logout, ["--keyring-only", "--config-only", "--api-host", HOST]
        )

        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    @pytest.mark.parametrize(
        "flag, skipped_attr, note_fragment",
        [
            (
                "--keyring-only",
                "find_existing_files",
                "credentials.ini was not modified",
            ),
            ("--config-only", "has_sso_tokens", "SSO tokens were not modified"),
        ],
    )
    def test_scoped_flags(self, runner, mock_deps, flag, skipped_attr, note_fragment):
        mock_creds, mock_keyring = mock_deps

        result = runner.invoke(logout, [flag, "--api-host", HOST])

        assert result.exit_code == 0
        # The skipped source should not have been touched
        target = mock_creds if hasattr(mock_creds, skipped_attr) else mock_keyring
        getattr(target, skipped_attr).assert_not_called()
        assert note_fragment in result.output

    @pytest.mark.parametrize(
        "env, expect_warning",
        [
            ({"CLOUDSMITH_API_KEY": "secret"}, True),
            ({}, False),
        ],
    )
    def test_env_api_key_warning(self, runner, mock_deps, env, expect_warning):
        with patch.dict(os.environ, env):
            result = runner.invoke(logout, ["--api-host", HOST])

        assert result.exit_code == 0
        if expect_warning:
            assert "unset CLOUDSMITH_API_KEY" in result.output
        else:
            assert "unset CLOUDSMITH_API_KEY" not in result.output

    def test_json_output(self, runner, mock_deps):
        """--output-format json emits structured JSON with expected keys."""
        _, mock_keyring = mock_deps
        mock_keyring.delete_sso_tokens.return_value = True

        result = runner.invoke(
            logout,
            ["--output-format", "json", "--api-host", HOST],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        # Human messages go to stderr; extract the JSON line from stdout.
        json_line = [
            line for line in result.output.splitlines() if line.startswith("{")
        ]
        assert json_line, f"No JSON found in output: {result.output!r}"
        payload = json.loads(json_line[0])
        data = payload["data"]
        assert data["api_host"] == HOST
        assert "dry_run" in data
        sources = data["sources"]
        assert "credential_file" in sources
        assert "keyring" in sources
        assert "environment_api_key" in sources

    def test_keyring_delete_failure(self, runner, mock_deps):
        """When delete_sso_tokens returns False, report failure."""
        _, mock_keyring = mock_deps
        mock_keyring.delete_sso_tokens.return_value = False

        result = runner.invoke(logout, ["--api-host", HOST])

        assert result.exit_code == 0
        assert "Failed to remove SSO tokens" in result.output
