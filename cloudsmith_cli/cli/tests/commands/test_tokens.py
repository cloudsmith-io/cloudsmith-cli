from unittest.mock import patch

import pytest

from cloudsmith_cli.cli.commands.tokens import list_tokens, refresh
from cloudsmith_cli.core.api.exceptions import ApiException


class MockToken:
    """Mock Token object with the properties needed for testing."""

    def __init__(self, key, created, slug_perm):
        self.key = key
        self.created = created
        self.slug_perm = slug_perm


@pytest.mark.usefixtures("set_api_host_env_var")
class TestListTokensCommand:

    def test_list_tokens_success(self, runner):
        """Test successful listing of tokens."""
        mock_tokens = [
            MockToken(
                key="abc123", created="2025-01-01T00:00:00Z", slug_perm="token-1"
            ),
            MockToken(
                key="def456", created="2025-01-02T00:00:00Z", slug_perm="token-2"
            ),
        ]

        with patch("cloudsmith_cli.core.api.user.list_user_tokens") as mock_list_tokens:
            mock_list_tokens.return_value = mock_tokens
            result = runner.invoke(list_tokens, [], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Retrieving API tokens... OK" in result.output
        assert "Token: abc123" in result.output
        assert "Created: 2025-01-01T00:00:00Z" in result.output
        assert "slug_perm: token-1" in result.output
        assert "Token: def456" in result.output
        assert "Created: 2025-01-02T00:00:00Z" in result.output
        assert "slug_perm: token-2" in result.output

    def test_list_tokens_error(self, runner):
        """Test error handling when listing tokens fails."""
        with patch("cloudsmith_cli.core.api.user.list_user_tokens") as mock_list_tokens:
            # Use ApiException for proper error handling
            mock_list_tokens.side_effect = ApiException("API error")
            result = runner.invoke(list_tokens, [], catch_exceptions=True)

        assert result.exit_code != 0

        # The error message might be in different places depending on how the exception is raised
        error_content = (
            str(getattr(result, "exception", "")) + result.output + result.stderr
        )
        assert (
            "API error" in error_content
            or "Failed to retrieve API tokens" in error_content
        )


@pytest.mark.usefixtures("set_api_host_env_var")
class TestRefreshTokenCommand:
    """Test suite for the 'tokens refresh' command."""

    def test_refresh_token_with_slug(self, runner):
        """Test successful refreshing of a token with a provided slug."""
        mock_new_token = MockToken(
            key="new_token_123",
            created="2025-01-03T00:00:00Z",
            slug_perm="token-refresh",
        )

        with patch(
            "cloudsmith_cli.core.api.user.refresh_user_token"
        ) as mock_refresh_token:
            mock_refresh_token.return_value = mock_new_token
            result = runner.invoke(refresh, ["token-refresh"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Refreshing token token-refresh... OK" in result.output
        assert "New token value: new_token_123" in result.output
        mock_refresh_token.assert_called_once_with("token-refresh")

    def test_refresh_token_error(self, runner):
        """Test error handling when refreshing a token fails."""
        with patch(
            "cloudsmith_cli.core.api.user.refresh_user_token"
        ) as mock_refresh_token:
            # Use ApiException for proper error handling
            mock_refresh_token.side_effect = ApiException("API error")
            result = runner.invoke(refresh, ["token-error"], catch_exceptions=True)

        assert result.exit_code != 0

        # The error message might be in different places depending on how the exception is raised
        error_content = (
            str(getattr(result, "exception", "")) + result.output + result.stderr
        )
        assert (
            "API error" in error_content
            or "Failed to refresh the token" in error_content
        )

    def test_refresh_token_list_error(self, runner):
        """Test error handling when listing tokens fails during refresh."""
        with patch("cloudsmith_cli.core.api.user.list_user_tokens") as mock_list_tokens:
            # Use ApiException for proper error handling
            mock_list_tokens.side_effect = ApiException("API error")
            result = runner.invoke(refresh, [], catch_exceptions=True)

        assert result.exit_code != 0

        # The error message might be in different places depending on how the exception is raised
        error_content = (
            str(getattr(result, "exception", "")) + result.output + result.stderr
        )
        assert (
            "API error" in error_content
            or "Failed to refresh the token" in error_content
        )
