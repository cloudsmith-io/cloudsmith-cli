"""Tests for the credentials file credential provider."""

from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.providers.credentials_file import (
    CredentialsFileProvider,
)


class TestCredentialsFileProvider:
    def test_resolves_from_file(self):
        provider = CredentialsFileProvider()
        context = CredentialContext(api_key_from_file="file-api-key-9012")
        result = provider.resolve(context)
        assert result is not None
        assert result.api_key == "file-api-key-9012"
        assert result.source_name == "credentials_file"
        assert result.auth_type == "api_key"
        assert "9012" in result.source_detail
        assert "credentials.ini" in result.source_detail

    def test_returns_none_when_not_set(self):
        provider = CredentialsFileProvider()
        context = CredentialContext(api_key_from_file=None)
        result = provider.resolve(context)
        assert result is None

    def test_returns_none_for_empty_string(self):
        provider = CredentialsFileProvider()
        context = CredentialContext(api_key_from_file="   ")
        result = provider.resolve(context)
        assert result is None

    def test_strips_whitespace(self):
        provider = CredentialsFileProvider()
        context = CredentialContext(api_key_from_file="  file-key  ")
        result = provider.resolve(context)
        assert result.api_key == "file-key"

    def test_ignores_flag_and_env_keys(self):
        provider = CredentialsFileProvider()
        context = CredentialContext(
            api_key_from_flag="flag-key",
            api_key_from_env="env-key",
            api_key_from_file=None,
        )
        result = provider.resolve(context)
        assert result is None
