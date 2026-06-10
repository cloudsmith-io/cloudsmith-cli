"""Tests for the CircleCI OIDC detector."""

from unittest import mock

import pytest

from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.oidc.detectors import detect_environment
from cloudsmith_cli.core.credentials.oidc.detectors.circleci import CircleCIDetector


@pytest.fixture
def circleci_env():
    env = {
        "CIRCLECI": "true",
        "CIRCLE_OIDC_TOKEN_V2": "the-v2-jwt",
        "CIRCLE_OIDC_TOKEN": "the-v1-jwt",
    }
    with mock.patch.dict("os.environ", env, clear=True):
        yield env


class TestDetect:
    def test_detects_when_circleci_and_v2_token_present(self, circleci_env):
        detector = CircleCIDetector(context=CredentialContext())
        assert detector.detect() is True

    def test_detects_with_only_v1_token(self, circleci_env):
        del circleci_env["CIRCLE_OIDC_TOKEN_V2"]
        with mock.patch.dict("os.environ", circleci_env, clear=True):
            detector = CircleCIDetector(context=CredentialContext())
            assert detector.detect() is True

    def test_not_detected_when_unset(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            detector = CircleCIDetector(context=CredentialContext())
            assert detector.detect() is False

    def test_not_detected_when_circleci_flag_missing(self, circleci_env):
        del circleci_env["CIRCLECI"]
        with mock.patch.dict("os.environ", circleci_env, clear=True):
            detector = CircleCIDetector(context=CredentialContext())
            assert detector.detect() is False

    def test_not_detected_without_any_token(self, circleci_env):
        del circleci_env["CIRCLE_OIDC_TOKEN_V2"]
        del circleci_env["CIRCLE_OIDC_TOKEN"]
        with mock.patch.dict("os.environ", circleci_env, clear=True):
            detector = CircleCIDetector(context=CredentialContext())
            assert detector.detect() is False


class TestGetToken:
    def test_prefers_v2_token(self, circleci_env):
        detector = CircleCIDetector(context=CredentialContext())
        assert detector.get_token() == "the-v2-jwt"

    def test_falls_back_to_v1_token(self, circleci_env):
        del circleci_env["CIRCLE_OIDC_TOKEN_V2"]
        with mock.patch.dict("os.environ", circleci_env, clear=True):
            detector = CircleCIDetector(context=CredentialContext())
            assert detector.get_token() == "the-v1-jwt"

    def test_raises_when_no_token(self, circleci_env):
        del circleci_env["CIRCLE_OIDC_TOKEN_V2"]
        del circleci_env["CIRCLE_OIDC_TOKEN"]
        with mock.patch.dict("os.environ", circleci_env, clear=True):
            detector = CircleCIDetector(context=CredentialContext())
            with pytest.raises(ValueError, match="CIRCLE_OIDC_TOKEN_V2"):
                detector.get_token()


class TestIntegration:
    def test_detect_environment_selects_circleci(self, circleci_env):
        detector = detect_environment(CredentialContext())
        assert isinstance(detector, CircleCIDetector)
