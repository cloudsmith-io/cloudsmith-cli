import json
from unittest.mock import patch

import pytest

from ...commands.login import login
from ...commands.main import main


@pytest.mark.usefixtures("set_api_host_env_var")
@pytest.mark.integration
class TestLoginCommand:
    def test_login_via_prompt(self, runner, username, password, api_key):
        """Test that a user can `cloudsmith login` with interactive prompts."""
        expected = f"Your API key/token is: {api_key}"
        user_input = [
            username,  # Login:
            password,  # Password:
            password,  # Repeat for confirmation:
            "N",  # No default config file(s) found, do you want to create them? [y/N]:
        ]
        result = runner.invoke(login, input="\n".join(user_input))
        assert not result.exception
        assert result.exit_code == 0
        assert expected in result.stdout

    def test_login_via_args(self, runner, username, password, api_key):
        """Test that a user can `cloudsmith login -l <login> -p <password>`."""
        expected = f"Your API key/token is: {api_key}"
        # The "input" argument here answers the following prompt:
        # No default config file(s) found, do you want to create them? [y/N]:
        result = runner.invoke(login, ["-l", username, "-p", password], input="N\n")
        assert not result.exception
        assert result.exit_code == 0
        assert expected in result.stdout


def invoke_main_login(runner, config_dir, name, *extra_args, user_input=None):
    """Run `cloudsmith <name>` through the registered command tree.

    The config and credentials paths point at an empty directory so a real
    config.ini or credentials.ini on the machine cannot change the result.
    """
    args = [
        name,
        "--config-file",
        str(config_dir),
        "--credentials-file",
        str(config_dir),
        "--api-host",
        "https://api.example.invalid",
        *extra_args,
    ]
    with (
        patch(
            "cloudsmith_cli.cli.commands.login.get_user_token",
            return_value="fake-api-key",
        ),
        patch(
            "cloudsmith_cli.cli.commands.login.create_config_files",
            return_value=(False, False),
        ),
        patch("cloudsmith_cli.cli.commands.login.new_config_messaging"),
    ):
        return runner.invoke(main, args, input=user_input)


@pytest.mark.parametrize("name", ["login", "token"])
class TestLoginDeprecation:
    """Login still works, but every invocation warns that it is going away."""

    def test_warns_on_stderr_and_still_returns_the_key(self, runner, tmp_path, name):
        result = invoke_main_login(
            runner, tmp_path, name, "-l", "you@example.com", "-p", "secret"
        )

        assert result.exit_code == 0
        assert f"DEPRECATION WARNING: 'cloudsmith {name}' is deprecated" in (
            result.stderr
        )
        assert "Personal API Keys" in result.stderr
        assert "cloudsmith auth" in result.stderr
        assert "DEPRECATION WARNING" not in result.stdout
        assert "Your API key/token is: fake-api-key" in result.stdout

    def test_warns_before_prompting_for_credentials(self, runner, tmp_path, name):
        result = invoke_main_login(
            runner,
            tmp_path,
            name,
            user_input="you@example.com\nsecret\nsecret\n",
        )

        assert result.exit_code == 0
        assert result.output.index("DEPRECATION WARNING") < result.output.index(
            "Login:"
        )

    def test_json_output_stays_parseable(self, runner, tmp_path, name):
        result = invoke_main_login(
            runner,
            tmp_path,
            name,
            "-l",
            "you@example.com",
            "-p",
            "secret",
            "--output-format",
            "json",
        )

        assert result.exit_code == 0
        assert "DEPRECATION WARNING" in result.stderr
        assert json.loads(result.stdout)["data"]["token"] == "fake-api-key"

    def test_help_marks_the_command_deprecated(self, runner, tmp_path, name):
        result = invoke_main_login(runner, tmp_path, name, "--help")

        assert result.exit_code == 0
        assert "[DEPRECATED]" in result.stdout


def test_shell_completion_parsing_does_not_warn(capsys):
    """Tab completion parses resiliently and must not print the warning."""
    login.make_context("login", ["-l", "you@example.com"], resilient_parsing=True)

    captured = capsys.readouterr()
    assert "DEPRECATION WARNING" not in captured.err
    assert "DEPRECATION WARNING" not in captured.out
