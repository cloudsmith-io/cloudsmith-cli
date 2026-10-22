import json
from unittest.mock import patch

import click.testing
import pytest

from ....core.credentials.models import CredentialResult
from ...commands.whoami import whoami

HOST = "https://api.example.com"
ARGS = ["--api-host", HOST, "--api-key", "fake-api-key"]
OIDC_SOURCE = "OIDC via GitHub Actions (org: acme, service: ci-service)"


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


def invoke_verbose_whoami(runner, credential, extra_args=None):
    """Invoke whoami --verbose with the credential chain resolving to credential."""
    with (
        patch(
            "cloudsmith_cli.cli.commands.whoami.get_user_brief",
            return_value=(True, "ci-service", None, "CI service"),
        ),
        patch(
            "cloudsmith_cli.core.credentials.chain.CredentialProviderChain.resolve",
            return_value=credential,
        ),
        patch(
            "cloudsmith_cli.cli.commands.whoami.keyring.has_sso_tokens",
            return_value=False,
        ),
    ):
        return runner.invoke(
            whoami, ["--api-host", HOST, "--verbose", *(extra_args or [])]
        )


def oidc_credential():
    """Return a credential as the OIDC provider resolves it after an exchange."""
    return CredentialResult(
        api_key="exchanged-token",
        source_name="oidc",
        source_detail=OIDC_SOURCE,
        auth_type="bearer",
    )


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


class TestWhoamiVerboseAuthMethod:
    """whoami --verbose names the method and the source of the credential in use."""

    def test_oidc_names_the_oidc_source(self, runner):
        """An OIDC token is sent as a bearer token, but it is not a SAML session."""
        result = invoke_verbose_whoami(runner, oidc_credential())

        assert result.exit_code == 0, result.output
        assert "Authentication Method: OIDC Auto-Discovery" in result.output
        assert f"  Source: {OIDC_SOURCE}" in result.output
        assert "SAML Token" not in result.output

    def test_json_oidc_names_the_oidc_source(self, runner):
        """The JSON output gives the method as oidc, with the source of the token."""
        result = invoke_verbose_whoami(
            runner, oidc_credential(), extra_args=["--output-format", "json"]
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(
            "".join(line for line in result.output.splitlines() if line.startswith("{"))
        )
        assert payload["data"]["auth"]["active_method"] == "oidc"
        assert payload["data"]["auth"]["oidc"] == {
            "configured": True,
            "source": OIDC_SOURCE,
        }

    def test_saml_session_is_still_a_saml_token(self, runner):
        """A bearer token from the keyring is a SAML session."""
        saml = CredentialResult(
            api_key="access-token",
            source_name="keyring",
            source_detail="System Keyring",
            auth_type="bearer",
        )

        result = invoke_verbose_whoami(runner, saml)

        assert result.exit_code == 0, result.output
        assert "Authentication Method: SAML Token (primary)" in result.output
        assert "OIDC" not in result.output
