"""Tests for the GitHub Actions OIDC detector."""

from unittest import mock

import pytest

from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.oidc.detectors import detect_environment
from cloudsmith_cli.core.credentials.oidc.detectors.github_actions import (
    GitHubActionsDetector,
)


@pytest.fixture
def github_env():
    env = {
        "GITHUB_ACTIONS": "true",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.actions.example/req",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "request-token",
    }
    with mock.patch.dict("os.environ", env, clear=True):
        yield env


class TestDetect:
    def test_detects_when_all_env_vars_present(self, github_env):
        detector = GitHubActionsDetector(context=CredentialContext())
        assert detector.detect() is True

    def test_not_detected_when_github_actions_unset(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            detector = GitHubActionsDetector(context=CredentialContext())
            assert detector.detect() is False

    def test_not_detected_without_request_url(self, github_env):
        del github_env["ACTIONS_ID_TOKEN_REQUEST_URL"]
        with mock.patch.dict("os.environ", github_env, clear=True):
            detector = GitHubActionsDetector(context=CredentialContext())
            assert detector.detect() is False

    def test_not_detected_without_request_token(self, github_env):
        del github_env["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]
        with mock.patch.dict("os.environ", github_env, clear=True):
            detector = GitHubActionsDetector(context=CredentialContext())
            assert detector.detect() is False


class TestGetToken:
    def _mock_session(self, json_data, status_ok=True):
        response = mock.Mock()
        response.json.return_value = json_data
        response.raise_for_status = mock.Mock()
        session = mock.Mock()
        session.get.return_value = response
        return session, response

    def test_returns_token_from_response(self, github_env):
        session, _ = self._mock_session({"value": "the-jwt"})
        context = CredentialContext(session=session)
        detector = GitHubActionsDetector(context=context)

        token = detector.get_token()

        assert token == "the-jwt"

    def test_requests_url_with_audience_and_auth_header(self, github_env):
        session, response = self._mock_session({"value": "the-jwt"})
        context = CredentialContext(session=session)
        detector = GitHubActionsDetector(context=context)

        detector.get_token()

        called_url = session.get.call_args[0][0]
        assert called_url.startswith("https://token.actions.example/req?audience=")
        assert "cloudsmith" in called_url
        headers = session.get.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer request-token"
        response.raise_for_status.assert_called_once()

    def test_uses_custom_audience(self, github_env):
        session, _ = self._mock_session({"value": "the-jwt"})
        context = CredentialContext(session=session, oidc_audience="my-aud")
        detector = GitHubActionsDetector(context=context)

        detector.get_token()

        called_url = session.get.call_args[0][0]
        assert "audience=my-aud" in called_url

    def test_appends_audience_with_ampersand_when_query_present(self, github_env):
        github_env["ACTIONS_ID_TOKEN_REQUEST_URL"] = (
            "https://token.actions.example/req?foo=bar"
        )
        with mock.patch.dict("os.environ", github_env, clear=True):
            session, _ = self._mock_session({"value": "the-jwt"})
            context = CredentialContext(session=session)
            detector = GitHubActionsDetector(context=context)

            detector.get_token()

            called_url = session.get.call_args[0][0]
            assert "?foo=bar&audience=" in called_url

    def test_raises_when_token_missing(self, github_env):
        session, _ = self._mock_session({})
        context = CredentialContext(session=session)
        detector = GitHubActionsDetector(context=context)

        with pytest.raises(ValueError):
            detector.get_token()


class TestIntegration:
    def test_detect_environment_selects_github_actions(self, github_env):
        detector = detect_environment(CredentialContext())
        assert isinstance(detector, GitHubActionsDetector)
