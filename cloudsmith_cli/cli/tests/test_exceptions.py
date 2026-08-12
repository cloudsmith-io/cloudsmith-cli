"""Tests for CLI error hints."""

from unittest.mock import Mock

from cloudsmith_cli.cli.exceptions import get_401_error_hint
from cloudsmith_cli.core.credentials.models import CredentialResult


def hint_for(credential, info_name="push"):
    """Return the 401 hint for a session holding the given credential.

    opts.api_key is left as an auto-Mock, so a hint that reads it rather than
    the resolved credential fails these tests.
    """
    return get_401_error_hint(
        Mock(info_name=info_name), Mock(credential=credential), Mock()
    )


class TestGet401ErrorHint:
    """The hint has to describe the credential the chain actually resolved.
    Branching on opts.api_key told OIDC sessions -- which never populate it --
    that they had no credentials at all.
    """

    def test_bearer_credential_suggests_reauthenticating(self):
        credential = CredentialResult(
            api_key="sso-token", source_name="keyring", auth_type="bearer"
        )

        assert "cloudsmith auth" in hint_for(credential)

    def test_api_key_credential_does_not_assert_a_permissions_problem(self):
        """A 401 means authentication failed, not that authorization was
        denied -- the hint shouldn't claim it's specifically a permissions
        issue, since that contradicts the 401 status line it's paired with.
        """
        credential = CredentialResult(api_key="csa_abc123", source_name="oidc")

        hint = hint_for(credential)

        assert "permission" not in hint
        assert "credentials" in hint

    def test_no_credential_suggests_authenticating(self):
        assert "cloudsmith token" in hint_for(None)

    def test_no_credential_on_token_command_reports_a_failed_login(self):
        assert "login failed" in hint_for(None, info_name="token")
