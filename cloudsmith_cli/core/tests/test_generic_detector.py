"""Tests for the generic fallback OIDC detector."""

from unittest import mock

import pytest

from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.oidc.detectors import detect_environment
from cloudsmith_cli.core.credentials.oidc.detectors.generic import GenericDetector


@pytest.fixture
def generic_env():
    env = {
        "CLOUDSMITH_OIDC_TOKEN": "the-jwt",
    }
    with mock.patch.dict("os.environ", env, clear=True):
        yield env


class TestDetect:
    def test_detects_when_token_present(self, generic_env):
        detector = GenericDetector(context=CredentialContext())
        assert detector.detect() is True

    def test_not_detected_when_unset(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            detector = GenericDetector(context=CredentialContext())
            assert detector.detect() is False

    def test_not_detected_when_token_empty(self, generic_env):
        generic_env["CLOUDSMITH_OIDC_TOKEN"] = ""
        with mock.patch.dict("os.environ", generic_env, clear=True):
            detector = GenericDetector(context=CredentialContext())
            assert detector.detect() is False

    def test_not_detected_when_token_whitespace_only(self, generic_env):
        generic_env["CLOUDSMITH_OIDC_TOKEN"] = "   \t\n"
        with mock.patch.dict("os.environ", generic_env, clear=True):
            detector = GenericDetector(context=CredentialContext())
            assert detector.detect() is False


class TestGetToken:
    def test_returns_token(self, generic_env):
        detector = GenericDetector(context=CredentialContext())
        assert detector.get_token() == "the-jwt"

    def test_strips_surrounding_whitespace(self, generic_env):
        generic_env["CLOUDSMITH_OIDC_TOKEN"] = "  the-jwt\n"
        with mock.patch.dict("os.environ", generic_env, clear=True):
            detector = GenericDetector(context=CredentialContext())
            assert detector.get_token() == "the-jwt"

    def test_raises_when_token_missing(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            detector = GenericDetector(context=CredentialContext())
            with pytest.raises(ValueError, match="CLOUDSMITH_OIDC_TOKEN"):
                detector.get_token()

    def test_raises_when_token_whitespace_only(self, generic_env):
        generic_env["CLOUDSMITH_OIDC_TOKEN"] = "   "
        with mock.patch.dict("os.environ", generic_env, clear=True):
            detector = GenericDetector(context=CredentialContext())
            with pytest.raises(ValueError, match="CLOUDSMITH_OIDC_TOKEN"):
                detector.get_token()


class TestIntegration:
    def test_detect_environment_selects_generic(self, generic_env):
        detector = detect_environment(
            CredentialContext(oidc_disabled_detectors=frozenset({"aws"}))
        )
        assert isinstance(detector, GenericDetector)
