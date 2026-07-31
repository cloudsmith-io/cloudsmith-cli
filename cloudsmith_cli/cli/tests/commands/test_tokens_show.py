import json
import os
import time
from datetime import datetime, timezone
from unittest import mock
from unittest.mock import patch

import click.testing
import jwt
import pytest

from ...commands.tokens import show
from ...config import ConfigReader, CredentialsReader

HOST = "https://api.example.com"
ARGS = ["--api-host", HOST]


@pytest.fixture()
def runner():
    return click.testing.CliRunner()


@pytest.fixture()
def isolated_config(tmp_path):
    """Keep credential resolution away from real env vars, configs and keyring."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLOUDSMITH_")}
    env.pop("GITHUB_ACTIONS", None)
    env["CLOUDSMITH_NO_KEYRING"] = "1"
    with (
        mock.patch.dict(os.environ, env, clear=True),
        patch.object(ConfigReader, "config_searchpath", [str(tmp_path)]),
        patch.object(CredentialsReader, "config_searchpath", [str(tmp_path)]),
    ):
        yield


def mock_oidc_session(vendor_token, exchanged_token):
    """Return a session mock covering the vendor token fetch and the exchange."""
    get_response = mock.Mock()
    get_response.json.return_value = {"value": vendor_token}
    post_response = mock.Mock()
    post_response.status_code = 200
    post_response.json.return_value = {"token": exchanged_token}
    session = mock.Mock()
    session.get.return_value = get_response
    session.post.return_value = post_response
    return session


def invoke_show_via_oidc(runner, exchanged_token, extra_args=None):
    """Invoke tokens show with GitHub Actions OIDC as the resolving source."""
    env = {
        "CLOUDSMITH_ORG": "example-org",
        "CLOUDSMITH_SERVICE_SLUG": "example-service",
        "GITHUB_ACTIONS": "true",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.actions.example/req",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "request-token",
    }
    session = mock_oidc_session("vendor-jwt", exchanged_token)
    with (
        mock.patch.dict(os.environ, env),
        patch(
            "cloudsmith_cli.core.credentials.oidc.cache.get_cached_token",
            return_value=None,
        ),
        patch("cloudsmith_cli.core.credentials.oidc.cache.store_cached_token"),
        patch("cloudsmith_cli.cli.decorators._create_session", return_value=session),
    ):
        return runner.invoke(show, ARGS + (extra_args or []), catch_exceptions=False)


def json_payload(result):
    return json.loads(
        "".join(line for line in result.output.splitlines() if line.startswith("{"))
    )


class TestTokensShowCommand:
    """Tests for the cloudsmith tokens show command."""

    def test_env_var_api_key_plain_output_is_token_only(self, runner, isolated_config):
        with mock.patch.dict(os.environ, {"CLOUDSMITH_API_KEY": "env-api-key"}):
            result = runner.invoke(show, ARGS, catch_exceptions=False)

        assert result.exit_code == 0
        assert result.stdout == "env-api-key\n"

    def test_env_var_api_key_json_output(self, runner, isolated_config):
        with mock.patch.dict(os.environ, {"CLOUDSMITH_API_KEY": "env-api-key"}):
            result = runner.invoke(
                show, ARGS + ["--output-format", "json"], catch_exceptions=False
            )

        assert result.exit_code == 0
        data = json_payload(result)["data"]
        assert data["token"] == "env-api-key"
        assert data["source"] == "env_var"
        assert data["auth_type"] == "api_key"
        assert "expires_at" not in data

    def test_oidc_resolved_plain_output_is_token_only(self, runner, isolated_config):
        result = invoke_show_via_oidc(runner, "exchanged-token")

        assert result.exit_code == 0
        assert result.stdout == "exchanged-token\n"

    def test_oidc_resolved_json_output_includes_expiry(self, runner, isolated_config):
        exp = int(time.time()) + 3600
        exchanged_token = jwt.encode({"exp": exp}, "s" * 32, algorithm="HS256")

        result = invoke_show_via_oidc(
            runner, exchanged_token, extra_args=["--output-format", "json"]
        )

        assert result.exit_code == 0
        data = json_payload(result)["data"]
        assert data["token"] == exchanged_token
        assert data["source"] == "oidc"
        expected_expiry = (
            datetime.fromtimestamp(exp, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        assert data["expires_at"] == expected_expiry

    def test_no_credentials_exits_nonzero(self, runner, isolated_config):
        result = runner.invoke(show, ARGS)

        assert result.exit_code == 1
        assert result.stdout == ""
        assert "No credentials could be resolved" in result.stderr

    def test_no_credentials_json_exits_nonzero(self, runner, isolated_config):
        result = runner.invoke(show, ARGS + ["--output-format", "json"])

        assert result.exit_code == 1
        assert "No credentials could be resolved" in result.stderr
