"""Tests for the CredentialContext class."""

from cloudsmith_cli.core.credentials import CredentialContext


class TestCredentialContext:
    def test_keyring_refresh_failed_defaults_false(self):
        context = CredentialContext()
        assert context.keyring_refresh_failed is False

    def test_keyring_refresh_failed_can_be_set(self):
        context = CredentialContext()
        context.keyring_refresh_failed = True
        assert context.keyring_refresh_failed is True
