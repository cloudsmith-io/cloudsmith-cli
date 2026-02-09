"""Tests for the auth command."""

from unittest.mock import MagicMock, patch

import pytest

from ...commands.auth import authenticate


class MockToken:
    """Mock Token object with the properties needed for testing."""

    def __init__(self, key, created, slug_perm):
        self.key = key
        self.created = created
        self.slug_perm = slug_perm

    def to_dict(self):
        return {
            "key": self.key,
            "created": self.created,
            "slug_perm": self.slug_perm,
        }


@pytest.fixture
def mock_saml_session():
    """Mock the SAML session creation."""
    with patch(
        "cloudsmith_cli.cli.commands.auth.create_configured_session"
    ) as mock_session:
        mock_session.return_value = MagicMock()
        yield mock_session


@pytest.fixture
def mock_get_idp_url():
    """Mock the IDP URL retrieval."""
    with patch("cloudsmith_cli.cli.commands.auth.get_idp_url") as mock_url:
        mock_url.return_value = "https://idp.example.com/saml"
        yield mock_url


@pytest.fixture
def mock_webbrowser():
    """Mock the webbrowser.open call."""
    with patch("cloudsmith_cli.cli.commands.auth.webbrowser") as mock_browser:
        yield mock_browser


@pytest.fixture
def mock_auth_server():
    """Mock the AuthenticationWebServer."""
    with patch(
        "cloudsmith_cli.cli.commands.auth.AuthenticationWebServer"
    ) as mock_server_class:
        mock_server_instance = MagicMock()
        mock_server_class.return_value = mock_server_instance
        yield mock_server_class


class TestAuthenticateCommand:
    """Tests for the authenticate command."""

    def test_auth_command_invokes_webserver(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify auth command creates AuthenticationWebServer."""
        runner.invoke(
            authenticate,
            ["--owner", "testorg"],
            catch_exceptions=False,
        )

        # Verify AuthenticationWebServer was called
        mock_auth_server.assert_called_once()

    def test_auth_command_opens_browser(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify auth command opens browser with IDP URL."""
        runner.invoke(
            authenticate,
            ["--owner", "testorg"],
            catch_exceptions=False,
        )

        # Verify browser was opened
        mock_webbrowser.open.assert_called_once_with("https://idp.example.com/saml")

    def test_auth_command_passes_owner_to_webserver(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify owner is passed to AuthenticationWebServer."""
        runner.invoke(
            authenticate,
            ["--owner", "testorg"],
            catch_exceptions=False,
        )

        # Verify AuthenticationWebServer was called with owner
        mock_auth_server.assert_called_once()
        call_kwargs = mock_auth_server.call_args.kwargs
        assert call_kwargs.get("owner") == "testorg"


class TestRequestApiKeyFlag:
    """Tests for the --request-api-key flag."""

    def test_request_api_key_creates_new_token(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify --request-api-key creates a new token and outputs only the key to stdout."""
        mock_token = MockToken(
            key="ck_test123456",
            created="2026-02-06T00:00:00Z",
            slug_perm="test-token",
        )

        with patch("cloudsmith_cli.cli.commands.auth.request_api_key") as mock_request:
            mock_request.return_value = mock_token
            result = runner.invoke(
                authenticate,
                ["--owner", "testorg", "--request-api-key"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        # The last line of output should be the raw token key
        output_lines = result.output.strip().split("\n")
        assert output_lines[-1] == "ck_test123456"
        mock_request.assert_called_once()

    def test_request_api_key_json_output(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify --request-api-key with --output-format json outputs JSON."""
        mock_token = MockToken(
            key="ck_test123456",
            created="2026-02-06T00:00:00Z",
            slug_perm="test-token",
        )

        with patch("cloudsmith_cli.cli.commands.auth.request_api_key") as mock_request:
            mock_request.return_value = mock_token
            result = runner.invoke(
                authenticate,
                ["--owner", "testorg", "--request-api-key", "--output-format", "json"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        # Should contain JSON data structure
        assert '"data"' in result.output
        assert '"key"' in result.output
        assert "ck_test123456" in result.output

    def test_request_api_key_mutual_exclusion_with_token(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify --request-api-key cannot be used with --token."""
        result = runner.invoke(
            authenticate,
            ["--owner", "testorg", "--request-api-key", "--token"],
            catch_exceptions=False,
        )

        assert result.exit_code != 0
        assert (
            "--request-api-key cannot be used with --token or --force" in result.output
        )

    def test_request_api_key_mutual_exclusion_with_force(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify --request-api-key cannot be used with --force."""
        result = runner.invoke(
            authenticate,
            ["--owner", "testorg", "--request-api-key", "--force"],
            catch_exceptions=False,
        )

        assert result.exit_code != 0
        assert (
            "--request-api-key cannot be used with --token or --force" in result.output
        )

    def test_request_api_key_with_save_config(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify --request-api-key with --save-config passes save_config=True."""
        mock_token = MockToken(
            key="ck_test123456",
            created="2026-02-06T00:00:00Z",
            slug_perm="test-token",
        )

        with patch("cloudsmith_cli.cli.commands.auth.request_api_key") as mock_request:
            mock_request.return_value = mock_token
            result = runner.invoke(
                authenticate,
                ["--owner", "testorg", "--request-api-key", "--save-config"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        # Verify save_config was passed
        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args.kwargs
        assert call_kwargs.get("save_config") is True

    def test_request_api_key_enables_token_creation_on_webserver(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify --request-api-key sets refresh_api_on_success=True on webserver."""
        mock_token = MockToken(
            key="ck_test123456",
            created="2026-02-06T00:00:00Z",
            slug_perm="test-token",
        )

        with patch("cloudsmith_cli.cli.commands.auth.request_api_key") as mock_request:
            mock_request.return_value = mock_token
            runner.invoke(
                authenticate,
                ["--owner", "testorg", "--request-api-key"],
                catch_exceptions=False,
            )

        # Verify AuthenticationWebServer was called with refresh_api_on_success=True
        mock_auth_server.assert_called_once()
        call_kwargs = mock_auth_server.call_args.kwargs
        assert call_kwargs.get("refresh_api_on_success") is True

    def test_request_api_key_failure_returns_nonzero_exit(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify --request-api-key exits non-zero when token retrieval fails."""
        with patch("cloudsmith_cli.cli.commands.auth.request_api_key") as mock_request:
            mock_request.return_value = None
            result = runner.invoke(
                authenticate,
                ["--owner", "testorg", "--request-api-key"],
                catch_exceptions=True,
            )

        assert result.exit_code != 0
        assert "Failed to retrieve API token" in result.output

    def test_request_api_key_clean_stdout(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify stdout ends with only the raw token key for easy capture.

        With --request-api-key, all informational messages are routed to stderr
        (via err=True), so only the raw token key should appear on stdout. In
        the CliRunner (which mixes stderr into output), the last line should be
        the raw key with no extra decoration.
        """
        mock_token = MockToken(
            key="ck_clean_output_test",
            created="2026-02-06T00:00:00Z",
            slug_perm="test-token",
        )

        with patch("cloudsmith_cli.cli.commands.auth.request_api_key") as mock_request:
            mock_request.return_value = mock_token
            result = runner.invoke(
                authenticate,
                ["--owner", "testorg", "--request-api-key"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        # The last output line must be the raw token key (no decoration)
        output_lines = result.output.strip().split("\n")
        assert output_lines[-1] == "ck_clean_output_test"

    def test_request_api_key_with_no_keyring_env(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify --request-api-key works with CLOUDSMITH_NO_KEYRING=1."""
        mock_token = MockToken(
            key="ck_no_keyring_test",
            created="2026-02-06T00:00:00Z",
            slug_perm="test-token",
        )

        with patch("cloudsmith_cli.cli.commands.auth.request_api_key") as mock_request:
            mock_request.return_value = mock_token
            result = runner.invoke(
                authenticate,
                ["--owner", "testorg", "--request-api-key"],
                catch_exceptions=False,
                env={"CLOUDSMITH_NO_KEYRING": "1"},
            )

        assert result.exit_code == 0
        output_lines = result.output.strip().split("\n")
        assert output_lines[-1] == "ck_no_keyring_test"
