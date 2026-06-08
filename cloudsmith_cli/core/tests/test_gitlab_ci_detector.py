"""Tests for the GitLab CI OIDC detector."""

from unittest import mock

import pytest

from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.oidc.detectors import detect_environment
from cloudsmith_cli.core.credentials.oidc.detectors.gitlab_ci import GitLabCIDetector


@pytest.fixture
def gitlab_env():
    env = {
        "GITLAB_CI": "true",
        "CLOUDSMITH_OIDC_TOKEN": "the-jwt",
    }
    with mock.patch.dict("os.environ", env, clear=True):
        yield env


class TestDetect:
    def test_detects_when_gitlab_ci_and_token_present(self, gitlab_env):
        detector = GitLabCIDetector(context=CredentialContext())
        assert detector.detect() is True

    def test_not_detected_when_unset(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            detector = GitLabCIDetector(context=CredentialContext())
            assert detector.detect() is False

    def test_not_detected_without_gitlab_ci_flag(self, gitlab_env):
        del gitlab_env["GITLAB_CI"]
        with mock.patch.dict("os.environ", gitlab_env, clear=True):
            detector = GitLabCIDetector(context=CredentialContext())
            assert detector.detect() is False

    def test_not_detected_when_gitlab_ci_not_true(self, gitlab_env):
        gitlab_env["GITLAB_CI"] = "false"
        with mock.patch.dict("os.environ", gitlab_env, clear=True):
            detector = GitLabCIDetector(context=CredentialContext())
            assert detector.detect() is False

    def test_not_detected_without_any_token(self, gitlab_env):
        del gitlab_env["CLOUDSMITH_OIDC_TOKEN"]
        with mock.patch.dict("os.environ", gitlab_env, clear=True):
            detector = GitLabCIDetector(context=CredentialContext())
            assert detector.detect() is False

    def test_not_detected_with_legacy_ci_job_jwt(self, gitlab_env):
        del gitlab_env["CLOUDSMITH_OIDC_TOKEN"]
        gitlab_env["CI_JOB_JWT_V2"] = "legacy-jwt"
        with mock.patch.dict("os.environ", gitlab_env, clear=True):
            detector = GitLabCIDetector(context=CredentialContext())
            assert detector.detect() is False


class TestGetToken:
    def test_returns_token(self, gitlab_env):
        detector = GitLabCIDetector(context=CredentialContext())
        assert detector.get_token() == "the-jwt"

    def test_raises_when_no_token(self, gitlab_env):
        del gitlab_env["CLOUDSMITH_OIDC_TOKEN"]
        with mock.patch.dict("os.environ", gitlab_env, clear=True):
            detector = GitLabCIDetector(context=CredentialContext())
            with pytest.raises(ValueError):
                detector.get_token()


class TestIntegration:
    def test_detect_environment_selects_gitlab_ci(self, gitlab_env):
        detector = detect_environment(CredentialContext())
        assert isinstance(detector, GitLabCIDetector)
