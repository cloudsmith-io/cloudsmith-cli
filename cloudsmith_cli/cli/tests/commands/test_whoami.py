import json
from unittest.mock import patch

import click.testing
import pytest

from ...commands.whoami import whoami

HOST = "https://api.example.com"
ARGS = ["--api-host", HOST, "--api-key", "fake-api-key"]


@pytest.fixture()
def runner():
    return click.testing.CliRunner()


def invoke_whoami(runner, user_brief, extra_args=None):
    """Invoke whoami with get_user_brief mocked to return user_brief."""
    with patch(
        "cloudsmith_cli.cli.commands.whoami.get_user_brief"
    ) as get_user_brief_mock:
        get_user_brief_mock.return_value = user_brief
        return runner.invoke(whoami, ARGS + (extra_args or []))


class TestWhoamiCommand:
    """Tests for the cloudsmith whoami command."""

    def test_authenticated_exits_zero(self, runner):
        result = invoke_whoami(
            runner, (True, "test-user", "test@example.com", "Test User")
        )

        assert result.exit_code == 0
        output = result.output.splitlines()
        assert output[0] == "Retrieving your authentication status from the API ... OK"
        assert output[1] == "You are authenticated as:"
        assert output[2] == "User: Test User (slug: test-user, email: test@example.com)"

    def test_unauthenticated_exits_one(self, runner):
        result = invoke_whoami(runner, (False, None, None, None))

        assert result.exit_code == 1
        output = result.output.splitlines()
        assert output[0] == "Retrieving your authentication status from the API ... OK"
        assert output[1] == "You are authenticated as:"
        assert output[2] == "Nobody (i.e. anonymous user)"

    def test_json_authenticated_exits_zero(self, runner):
        result = invoke_whoami(
            runner,
            (True, "test-user", "test@example.com", "Test User"),
            extra_args=["--output-format", "json"],
        )

        assert result.exit_code == 0
        payload = json.loads(
            "".join(line for line in result.output.splitlines() if line.startswith("{"))
        )
        assert payload["data"]["is_authenticated"] is True
        assert payload["data"]["username"] == "test-user"

    def test_json_unauthenticated_exits_one(self, runner):
        result = invoke_whoami(
            runner, (False, None, None, None), extra_args=["--output-format", "json"]
        )

        assert result.exit_code == 1
        payload = json.loads(
            "".join(line for line in result.output.splitlines() if line.startswith("{"))
        )
        assert payload["data"]["is_authenticated"] is False
