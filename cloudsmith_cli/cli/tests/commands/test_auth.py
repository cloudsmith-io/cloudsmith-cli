"""Tests for the auth command."""

import json
import webbrowser
from unittest.mock import MagicMock, patch

import pytest

from ....core.api.exceptions import ApiException
from ...commands.auth import authenticate
from ...commands.main import main
from .conftest import MockToken


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

    @pytest.mark.parametrize(
        "option",
        [
            "--workspace",
            "-w",
            "--org",
            "--organization",
            "--oidc-org",
            "--owner",
            "-o",
        ],
    )
    def test_workspace_option_aliases(
        self,
        option,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Current and legacy option spellings identify the same Workspace."""
        result = runner.invoke(
            authenticate,
            [option, "test-workspace", "--no-browser"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert mock_auth_server.call_args.kwargs["owner"] == "test-workspace"

    @pytest.mark.parametrize("envvar", ["CLOUDSMITH_WORKSPACE", "CLOUDSMITH_ORG"])
    def test_workspace_environment_aliases(
        self,
        envvar,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Authentication inherits either Workspace environment variable."""
        result = runner.invoke(
            authenticate,
            ["--no-browser"],
            env={envvar: "test-workspace"},
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert mock_auth_server.call_args.kwargs["owner"] == "test-workspace"

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
        mock_webbrowser.open.return_value = True

        result = runner.invoke(
            authenticate,
            ["--owner", "testorg"],
            catch_exceptions=False,
        )

        # Verify browser was opened
        assert "Couldn't open a browser automatically" not in result.output
        mock_webbrowser.open.assert_called_once_with("https://idp.example.com/saml")
        mock_auth_server.return_value.handle_request.assert_called_once()

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


class TestBrowserFallback:
    """Tests for graceful handling of webbrowser.open() failures."""

    def test_webbrowser_error_does_not_crash(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify a webbrowser.Error from webbrowser.open() doesn't crash the command."""
        mock_webbrowser.open.side_effect = webbrowser.Error("no runnable browser found")

        result = runner.invoke(
            main,
            ["authenticate", "--owner", "testorg"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Couldn't open a browser automatically" in result.output
        mock_webbrowser.open.assert_called_once_with("https://idp.example.com/saml")
        mock_auth_server.assert_called_once()
        mock_auth_server.return_value.handle_request.assert_called_once()

    def test_false_return_from_open_uses_manual_fallback(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify a false return from webbrowser.open() uses the manual fallback."""
        mock_webbrowser.open.return_value = False

        result = runner.invoke(
            main,
            ["auth", "--owner", "testorg"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Couldn't open a browser automatically" in result.output
        mock_webbrowser.open.assert_called_once_with("https://idp.example.com/saml")
        mock_auth_server.return_value.handle_request.assert_called_once()

    def test_generic_exception_from_open_does_not_crash(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify any unexpected exception from webbrowser.open() also degrades gracefully."""
        mock_webbrowser.open.side_effect = RuntimeError("platform-specific failure")

        result = runner.invoke(
            main,
            ["auth", "--owner", "testorg"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Couldn't open a browser automatically" in result.output
        mock_auth_server.assert_called_once()
        mock_auth_server.return_value.handle_request.assert_called_once()


class TestNoBrowserFlag:
    """Tests for the --no-browser flag."""

    def test_no_browser_skips_webbrowser_open(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify --no-browser never calls webbrowser.open()."""
        result = runner.invoke(
            main,
            ["auth", "--owner", "testorg", "--no-browser"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        mock_webbrowser.open.assert_not_called()
        assert "Skipping automatic browser launch" in result.output
        assert "Opening your Workspace's SAML IDP URL" not in result.output
        assert "Your Workspace's SAML IDP URL is:" in result.output
        mock_auth_server.assert_called_once()
        mock_auth_server.return_value.handle_request.assert_called_once()


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

    def test_token_option_is_rejected(self, runner):
        """Verify the removed --token option is rejected."""
        result = runner.invoke(authenticate, ["--token"])

        assert result.exit_code != 0
        assert "No such option '--token'" in result.output

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
        assert "--request-api-key cannot be used with --force" in result.output

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


class TestAuthFailureOutputModes:
    """Tests for auth error routing in default and JSON modes."""

    def test_json_mode_writes_error_json_to_stdout(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify auth failures in -F json emit only JSON on stdout."""
        mock_auth_server.return_value.handle_request.side_effect = ApiException(
            422, detail="Invalid input."
        )

        result = runner.invoke(
            main,
            ["auth", "--owner", "testorg", "-F", "json"],
            catch_exceptions=False,
        )

        payload = json.loads(result.stdout)
        assert payload["detail"] == "Invalid input."
        assert payload["meta"]["code"] == 422
        assert "Beginning authentication for the testorg Workspace" in result.stderr
        assert "Beginning authentication for the testorg org" not in result.stdout
