"""Integration tests proving correct credential resolution priority.

Priority (highest → lowest):
    --api-key CLI flag > CLOUDSMITH_API_KEY env var > credentials.ini > keyring SSO
"""

from unittest.mock import patch

from cloudsmith_cli.core import keyring
from cloudsmith_cli.core.credentials.chain import CredentialProviderChain
from cloudsmith_cli.core.credentials.models import CredentialContext


class TestCredentialChainPriority:
    def _context(self, **kwargs):
        return CredentialContext(
            api_host="https://api.cloudsmith.io",
            **kwargs,
        )

    def test_cli_flag_beats_keyring(self):
        """Explicit --api-key must win over a keyring SSO token."""
        context = self._context(api_key_from_flag="explicit-flag-key")

        with patch.object(keyring, "should_use_keyring", return_value=True):
            with patch.object(keyring, "get_access_token", return_value="sso-token"):
                with patch.object(
                    keyring, "should_refresh_access_token", return_value=False
                ):
                    chain = CredentialProviderChain()
                    result = chain.resolve(context)

        assert result is not None
        assert result.api_key == "explicit-flag-key"
        assert result.source_name == "cli_flag"

    def test_env_var_beats_keyring(self):
        """CLOUDSMITH_API_KEY env var must win over keyring SSO."""
        context = self._context(api_key_from_env="env-key")

        with patch.object(keyring, "should_use_keyring", return_value=True):
            with patch.object(keyring, "get_access_token", return_value="sso-token"):
                with patch.object(
                    keyring, "should_refresh_access_token", return_value=False
                ):
                    chain = CredentialProviderChain()
                    result = chain.resolve(context)

        assert result is not None
        assert result.api_key == "env-key"
        assert result.source_name == "env_var"

    def test_credentials_file_beats_keyring(self):
        """credentials.ini must win over keyring SSO."""
        context = self._context(api_key_from_file="file-key")

        with patch.object(keyring, "should_use_keyring", return_value=True):
            with patch.object(keyring, "get_access_token", return_value="sso-token"):
                with patch.object(
                    keyring, "should_refresh_access_token", return_value=False
                ):
                    chain = CredentialProviderChain()
                    result = chain.resolve(context)

        assert result is not None
        assert result.api_key == "file-key"
        assert result.source_name == "credentials_file"

    def test_cli_flag_beats_env_var(self):
        """--api-key CLI flag must win over CLOUDSMITH_API_KEY env var."""
        context = self._context(
            api_key_from_flag="flag-key",
            api_key_from_env="env-key",
        )

        chain = CredentialProviderChain()
        result = chain.resolve(context)

        assert result is not None
        assert result.api_key == "flag-key"
        assert result.source_name == "cli_flag"

    def test_cli_flag_beats_credentials_file(self):
        """--api-key CLI flag must win over credentials.ini key."""
        context = self._context(
            api_key_from_flag="flag-key",
            api_key_from_file="file-key",
        )

        chain = CredentialProviderChain()
        result = chain.resolve(context)

        assert result is not None
        assert result.api_key == "flag-key"
        assert result.source_name == "cli_flag"

    def test_env_var_beats_credentials_file(self):
        """CLOUDSMITH_API_KEY env var must win over credentials.ini key."""
        context = self._context(
            api_key_from_env="env-key",
            api_key_from_file="file-key",
        )

        chain = CredentialProviderChain()
        result = chain.resolve(context)

        assert result is not None
        assert result.api_key == "env-key"
        assert result.source_name == "env_var"

    def test_keyring_used_when_no_explicit_key(self):
        """Keyring SSO is the fallback when no explicit keys are set."""
        context = self._context()

        with patch.object(keyring, "should_use_keyring", return_value=True):
            with patch.object(keyring, "get_access_token", return_value="sso-token"):
                with patch.object(
                    keyring, "should_refresh_access_token", return_value=False
                ):
                    chain = CredentialProviderChain()
                    result = chain.resolve(context)

        assert result is not None
        assert result.api_key == "sso-token"
        assert result.source_name == "keyring"

    def test_no_credentials_returns_none(self):
        """Returns None when no source provides credentials."""
        context = self._context()

        with patch.object(keyring, "should_use_keyring", return_value=False):
            chain = CredentialProviderChain()
            result = chain.resolve(context)

        assert result is None
