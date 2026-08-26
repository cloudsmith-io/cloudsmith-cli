"""Tests for the Bitbucket Pipelines OIDC detector."""

from unittest import mock

import pytest

from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.oidc.detectors import detect_environment
from cloudsmith_cli.core.credentials.oidc.detectors.bitbucket_pipelines import (
    BitbucketPipelinesDetector,
)


@pytest.fixture
def bitbucket_env():
    env = {
        "BITBUCKET_STEP_OIDC_TOKEN": "the-jwt",
    }
    with mock.patch.dict("os.environ", env, clear=True):
        yield env


class TestDetect:
    def test_detects_when_token_present(self, bitbucket_env):
        detector = BitbucketPipelinesDetector(context=CredentialContext())
        assert detector.detect() is True

    def test_not_detected_when_unset(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            detector = BitbucketPipelinesDetector(context=CredentialContext())
            assert detector.detect() is False

    def test_not_detected_when_token_empty(self, bitbucket_env):
        bitbucket_env["BITBUCKET_STEP_OIDC_TOKEN"] = ""
        with mock.patch.dict("os.environ", bitbucket_env, clear=True):
            detector = BitbucketPipelinesDetector(context=CredentialContext())
            assert detector.detect() is False


class TestGetToken:
    def test_returns_token(self, bitbucket_env):
        detector = BitbucketPipelinesDetector(context=CredentialContext())
        assert detector.get_token() == "the-jwt"

    def test_raises_when_token_missing(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            detector = BitbucketPipelinesDetector(context=CredentialContext())
            with pytest.raises(ValueError):
                detector.get_token()


class TestIntegration:
    def test_detect_environment_selects_bitbucket_pipelines(self, bitbucket_env):
        detector = detect_environment(CredentialContext())
        assert isinstance(detector, BitbucketPipelinesDetector)
