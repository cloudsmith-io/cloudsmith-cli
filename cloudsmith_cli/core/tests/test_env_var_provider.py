"""Tests for the environment variable credential provider."""

from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.providers.env_var import EnvVarProvider


class TestEnvVarProvider:
    def test_resolves_from_env(self):
        provider = EnvVarProvider()
        context = CredentialContext(api_key_from_env="env-api-key-5678")
        result = provider.resolve(context)
        assert result is not None
        assert result.api_key == "env-api-key-5678"
        assert result.source_name == "env_var"
        assert result.auth_type == "api_key"
        assert "5678" in result.source_detail
        assert "CLOUDSMITH_API_KEY" in result.source_detail

    def test_returns_none_when_not_set(self):
        provider = EnvVarProvider()
        context = CredentialContext(api_key_from_env=None)
        result = provider.resolve(context)
        assert result is None

    def test_returns_none_for_empty_string(self):
        provider = EnvVarProvider()
        context = CredentialContext(api_key_from_env="  ")
        result = provider.resolve(context)
        assert result is None

    def test_strips_whitespace(self):
        provider = EnvVarProvider()
        context = CredentialContext(api_key_from_env="  my-env-key  ")
        result = provider.resolve(context)
        assert result.api_key == "my-env-key"

    def test_ignores_flag_and_file_keys(self):
        provider = EnvVarProvider()
        context = CredentialContext(
            api_key_from_flag="flag-key",
            api_key_from_env=None,
            api_key_from_file="file-key",
        )
        result = provider.resolve(context)
        assert result is None
