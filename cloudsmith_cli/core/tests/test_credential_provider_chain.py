"""Tests for the credential provider chain."""

from cloudsmith_cli.core.credentials import (
    CredentialContext,
    CredentialProvider,
    CredentialProviderChain,
    CredentialResult,
)


class DummyProvider(CredentialProvider):
    """Test provider that returns a configurable result."""

    def __init__(self, name, result=None, should_raise=False):
        self.name = name
        self._result = result
        self._should_raise = should_raise

    def resolve(self, context):
        if self._should_raise:
            raise RuntimeError("Provider error")
        return self._result


class TestCredentialProviderChain:
    def test_first_provider_wins(self):
        result1 = CredentialResult(api_key="key1", source_name="first")
        result2 = CredentialResult(api_key="key2", source_name="second")
        chain = CredentialProviderChain(
            [
                DummyProvider("p1", result=result1),
                DummyProvider("p2", result=result2),
            ]
        )
        result = chain.resolve(CredentialContext())
        assert result.api_key == "key1"
        assert result.source_name == "first"

    def test_falls_through_to_second(self):
        result2 = CredentialResult(api_key="key2", source_name="second")
        chain = CredentialProviderChain(
            [
                DummyProvider("p1", result=None),
                DummyProvider("p2", result=result2),
            ]
        )
        result = chain.resolve(CredentialContext())
        assert result.api_key == "key2"

    def test_returns_none_when_all_fail(self):
        chain = CredentialProviderChain(
            [
                DummyProvider("p1", result=None),
                DummyProvider("p2", result=None),
            ]
        )
        result = chain.resolve(CredentialContext())
        assert result is None

    def test_skips_erroring_provider(self):
        result2 = CredentialResult(api_key="key2", source_name="second")
        chain = CredentialProviderChain(
            [
                DummyProvider("p1", should_raise=True),
                DummyProvider("p2", result=result2),
            ]
        )
        result = chain.resolve(CredentialContext())
        assert result.api_key == "key2"

    def test_empty_chain(self):
        chain = CredentialProviderChain([])
        result = chain.resolve(CredentialContext())
        assert result is None

    def test_default_chain_order(self):
        chain = CredentialProviderChain()
        assert len(chain.providers) == 3
        assert chain.providers[0].name == "keyring"
        assert chain.providers[1].name == "cli_flag"
        assert chain.providers[2].name == "oidc"
