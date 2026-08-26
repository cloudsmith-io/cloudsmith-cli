"""Tests for the CLI flag credential provider."""

from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.providers import CLIFlagProvider


class TestCLIFlagProvider:
    def test_resolves_from_flag(self):
        provider = CLIFlagProvider()
        context = CredentialContext(api_key_from_flag="my-api-key-1234")
        result = provider.resolve(context)
        assert result is not None
        assert result.api_key == "my-api-key-1234"
        assert result.source_name == "cli_flag"
        assert result.auth_type == "api_key"
        assert "1234" in result.source_detail
        assert "--api-key" in result.source_detail

    def test_returns_none_when_not_set(self):
        provider = CLIFlagProvider()
        context = CredentialContext(api_key_from_flag=None)
        result = provider.resolve(context)
        assert result is None

    def test_returns_none_for_empty_value(self):
        provider = CLIFlagProvider()
        context = CredentialContext(api_key_from_flag="  ")
        result = provider.resolve(context)
        assert result is None

    def test_strips_whitespace(self):
        provider = CLIFlagProvider()
        context = CredentialContext(api_key_from_flag="  my-key  ")
        result = provider.resolve(context)
        assert result.api_key == "my-key"

    def test_ignores_env_and_file_keys(self):
        """CLIFlagProvider must not resolve keys from other sources."""
        provider = CLIFlagProvider()
        context = CredentialContext(
            api_key_from_flag=None,
            api_key_from_env="env-key",
            api_key_from_file="file-key",
        )
        result = provider.resolve(context)
        assert result is None
