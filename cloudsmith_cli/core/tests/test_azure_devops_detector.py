"""Tests for the Azure DevOps OIDC detector."""

from unittest import mock

import pytest

from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.oidc.detectors import detect_environment
from cloudsmith_cli.core.credentials.oidc.detectors.azure_devops import (
    AzureDevOpsDetector,
)


@pytest.fixture
def azure_env():
    env = {
        "SYSTEM_OIDCREQUESTURI": "https://dev.azure.example/oidc/req",
        "SYSTEM_ACCESSTOKEN": "access-token",
    }
    with mock.patch.dict("os.environ", env, clear=True):
        yield env


class TestDetect:
    def test_detects_when_all_env_vars_present(self, azure_env):
        detector = AzureDevOpsDetector(context=CredentialContext())
        assert detector.detect() is True

    def test_not_detected_when_unset(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            detector = AzureDevOpsDetector(context=CredentialContext())
            assert detector.detect() is False

    def test_not_detected_without_request_uri(self, azure_env):
        del azure_env["SYSTEM_OIDCREQUESTURI"]
        with mock.patch.dict("os.environ", azure_env, clear=True):
            detector = AzureDevOpsDetector(context=CredentialContext())
            assert detector.detect() is False

    def test_not_detected_without_access_token(self, azure_env):
        del azure_env["SYSTEM_ACCESSTOKEN"]
        with mock.patch.dict("os.environ", azure_env, clear=True):
            detector = AzureDevOpsDetector(context=CredentialContext())
            assert detector.detect() is False


class TestGetToken:
    def _mock_session(self, json_data):
        response = mock.Mock()
        response.json.return_value = json_data
        response.raise_for_status = mock.Mock()
        session = mock.Mock()
        session.post.return_value = response
        return session, response

    def test_returns_token_from_response(self, azure_env):
        session, _ = self._mock_session({"oidcToken": "the-jwt"})
        context = CredentialContext(session=session)
        detector = AzureDevOpsDetector(context=context)

        token = detector.get_token()

        assert token == "the-jwt"

    def test_posts_empty_body_with_api_version_and_auth_header(self, azure_env):
        session, response = self._mock_session({"oidcToken": "the-jwt"})
        context = CredentialContext(session=session)
        detector = AzureDevOpsDetector(context=context)

        detector.get_token()

        called_url = session.post.call_args[0][0]
        assert called_url == "https://dev.azure.example/oidc/req?api-version=7.1"
        kwargs = session.post.call_args[1]
        # Azure DevOps ignores any requested audience and mints a token with a
        # fixed audience, so no body is sent (matching the Azure SDK).
        assert kwargs.get("json") is None
        assert kwargs.get("data") is None
        assert kwargs["headers"]["Authorization"] == "Bearer access-token"
        assert kwargs["headers"]["X-TFS-FedAuthRedirect"] == "Suppress"
        response.raise_for_status.assert_called_once()

    def test_appends_api_version_with_ampersand_when_query_present(self, azure_env):
        azure_env["SYSTEM_OIDCREQUESTURI"] = (
            "https://dev.azure.example/oidc/req?foo=bar"
        )
        with mock.patch.dict("os.environ", azure_env, clear=True):
            session, _ = self._mock_session({"oidcToken": "the-jwt"})
            context = CredentialContext(session=session)
            detector = AzureDevOpsDetector(context=context)

            detector.get_token()

            called_url = session.post.call_args[0][0]
            assert (
                called_url
                == "https://dev.azure.example/oidc/req?foo=bar&api-version=7.1"
            )

    def test_custom_audience_is_ignored(self, azure_env):
        # Azure DevOps does not support a caller-supplied audience, so even a
        # custom oidc_audience must not add a request body.
        session, _ = self._mock_session({"oidcToken": "the-jwt"})
        context = CredentialContext(session=session, oidc_audience="my-aud")
        detector = AzureDevOpsDetector(context=context)

        detector.get_token()

        kwargs = session.post.call_args[1]
        assert kwargs.get("json") is None
        assert kwargs.get("data") is None

    def test_raises_when_token_missing(self, azure_env):
        session, _ = self._mock_session({})
        context = CredentialContext(session=session)
        detector = AzureDevOpsDetector(context=context)

        with pytest.raises(ValueError):
            detector.get_token()


class TestIntegration:
    def test_detect_environment_selects_azure_devops(self, azure_env):
        detector = detect_environment(CredentialContext())
        assert isinstance(detector, AzureDevOpsDetector)
