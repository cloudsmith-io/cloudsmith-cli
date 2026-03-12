"""Tests for the CLI flag credential provider."""

from cloudsmith_cli.core.credentials import CredentialContext
from cloudsmith_cli.core.credentials.providers import CLIFlagProvider


class TestCLIFlagProvider:
    def test_resolves_from_context(self):
        provider = CLIFlagProvider()
        context = CredentialContext(api_key="my-api-key-1234")
        result = provider.resolve(context)
        assert result is not None
        assert result.api_key == "my-api-key-1234"
        assert result.source_name == "cli_flag"
        assert result.auth_type == "api_key"
        assert "1234" in result.source_detail

    def test_returns_none_when_not_set(self):
        provider = CLIFlagProvider()
        context = CredentialContext(api_key=None)
        result = provider.resolve(context)
        assert result is None

    def test_returns_none_for_empty_value(self):
        provider = CLIFlagProvider()
        context = CredentialContext(api_key="  ")
        result = provider.resolve(context)
        assert result is None

    def test_strips_whitespace(self):
        provider = CLIFlagProvider()
        context = CredentialContext(api_key="  my-key  ")
        result = provider.resolve(context)
        assert result.api_key == "my-key"
