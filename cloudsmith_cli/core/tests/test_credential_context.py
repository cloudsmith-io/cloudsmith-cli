"""Tests for the CredentialContext class."""

from cloudsmith_cli.core.credentials.models import CredentialContext


class TestCredentialContext:
    def test_all_key_sources_default_none(self):
        context = CredentialContext()
        assert context.api_key_from_flag is None
        assert context.api_key_from_env is None
        assert context.api_key_from_file is None

    def test_keyring_refresh_failed_defaults_false(self):
        context = CredentialContext()
        assert context.keyring_refresh_failed is False

    def test_keyring_refresh_failed_can_be_set(self):
        context = CredentialContext()
        context.keyring_refresh_failed = True
        assert context.keyring_refresh_failed is True

    def test_per_source_fields_are_independent(self):
        context = CredentialContext(
            api_key_from_flag="flag-key",
            api_key_from_env="env-key",
            api_key_from_file="file-key",
        )
        assert context.api_key_from_flag == "flag-key"
        assert context.api_key_from_env == "env-key"
        assert context.api_key_from_file == "file-key"
