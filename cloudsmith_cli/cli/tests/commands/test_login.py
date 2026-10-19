import json
from contextlib import ExitStack
from unittest.mock import Mock, patch

import pytest

from ....core.api.exceptions import ApiException, TwoFactorRequiredException
from ...commands.login import API_KEY_DOCS_URL, REMOVED_MESSAGE, login
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


def invoke_main_login(
    runner,
    config_dir,
    name,
    *extra_args,
    user_input=None,
    get_user_token=None,
):
    """Run `cloudsmith <name>` through the registered command tree.

    The config and credentials paths point at an empty directory so a real
    config.ini or credentials.ini on the machine cannot change the result.
    ``get_user_token`` replaces the API call (default: return a fake key).
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
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "cloudsmith_cli.cli.commands.login.get_user_token",
                get_user_token or Mock(return_value="fake-api-key"),
            )
        )
        stack.enter_context(
            patch(
                "cloudsmith_cli.cli.commands.login.create_config_files",
                return_value=(False, False),
            )
        )
        stack.enter_context(
            patch("cloudsmith_cli.cli.commands.login.new_config_messaging")
        )
        return runner.invoke(main, args, input=user_input)


@pytest.mark.parametrize("name", ["login", "token"])
class TestLoginDeprecation:
    """Login still works, but every invocation warns that it is going away."""

    def test_warns_on_stderr_and_still_returns_the_key(self, runner, tmp_path, name):
        result = invoke_main_login(
            runner, tmp_path, name, "-l", "you@example.com", "-p", "secret"
        )

        assert result.exit_code == 0
        assert f"Warning: `cloudsmith {name}` is deprecated" in result.stderr
        assert "Personal API Keys" in result.stderr
        assert "cloudsmith auth" in result.stderr
        assert "Use an API key or SAML instead" in result.stderr
        assert "log in with SAML." in result.stderr
        assert "sso" not in result.stderr.lower()
        assert "https://cloudsmith.com/changelog" in result.stderr
        assert f"More: {API_KEY_DOCS_URL}" in result.stderr
        assert "is deprecated" not in result.stdout
        assert "Your API key/token is: fake-api-key" in result.stdout

    def test_warns_before_prompting_for_credentials(self, runner, tmp_path, name):
        result = invoke_main_login(
            runner,
            tmp_path,
            name,
            user_input="you@example.com\nsecret\nsecret\n",
        )

        assert result.exit_code == 0
        assert result.output.index("is deprecated") < result.output.index("Login:")

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
        assert "is deprecated" in result.stderr
        assert json.loads(result.stdout)["data"]["token"] == "fake-api-key"

    def test_help_marks_the_command_deprecated(self, runner, tmp_path, name):
        result = invoke_main_login(runner, tmp_path, name, "--help")

        assert result.exit_code == 0
        assert "[DEPRECATED]" in result.stdout
        assert API_KEY_DOCS_URL in result.stdout
        assert "log in with SAML." in result.stdout
        assert "sso" not in result.stdout.lower()


def test_shell_completion_parsing_does_not_warn(capsys):
    """Tab completion parses resiliently and must not print the warning."""
    login.make_context("login", ["-l", "you@example.com"], resilient_parsing=True)

    captured = capsys.readouterr()
    assert "is deprecated" not in captured.err
    assert "is deprecated" not in captured.out


@pytest.mark.parametrize("name", ["login", "token"])
@pytest.mark.parametrize("status", [404, 410])
class TestLoginSwitchedOff:
    """Once the server switches the endpoint off, say so instead of a raw error."""

    @staticmethod
    def switched_off(status):
        return Mock(side_effect=ApiException(status, detail="Gone."))

    def test_reports_removal(self, runner, tmp_path, name, status):
        result = invoke_main_login(
            runner,
            tmp_path,
            name,
            "-l",
            "you@example.com",
            "-p",
            "secret",
            get_user_token=self.switched_off(status),
        )

        assert result.return_value == status
        assert REMOVED_MESSAGE in result.output
        assert "log in with SAML." in result.output
        assert "sso" not in result.output.lower()
        assert f"More: {API_KEY_DOCS_URL}" in result.output
        assert f"status: {status}" not in result.output
        assert "usually means the user/org is wrong" not in result.output

    def test_json_reports_removal(self, runner, tmp_path, name, status):
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
            get_user_token=self.switched_off(status),
        )

        error = json.loads(result.stdout)
        assert result.return_value == status
        assert error["detail"] == REMOVED_MESSAGE
        assert error["meta"]["code"] == status
        assert error["help"]["hint"] is None

    def test_reports_removal_after_two_factor(self, runner, tmp_path, name, status):
        get_user_token = Mock(
            side_effect=[
                TwoFactorRequiredException("2fa-token"),
                ApiException(status, detail="Gone."),
            ]
        )

        result = invoke_main_login(
            runner,
            tmp_path,
            name,
            "-l",
            "you@example.com",
            "-p",
            "secret",
            user_input="123456\n",
            get_user_token=get_user_token,
        )

        assert result.return_value == status
        assert REMOVED_MESSAGE in result.output


@pytest.mark.parametrize("status", [401, 500, 503])
def test_other_errors_keep_the_standard_rendering(runner, tmp_path, status):
    """An outage or bad credentials must not be reported as a removal."""
    result = invoke_main_login(
        runner,
        tmp_path,
        "login",
        "-l",
        "you@example.com",
        "-p",
        "secret",
        get_user_token=Mock(side_effect=ApiException(status, detail="Nope.")),
    )

    assert result.return_value == status
    assert REMOVED_MESSAGE not in result.output
    assert f"status: {status}" in result.output
