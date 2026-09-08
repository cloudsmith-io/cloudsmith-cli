"""Tests for the Buildkite OIDC detector."""

import subprocess
from unittest import mock

import pytest

from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.oidc.detectors import detect_environment
from cloudsmith_cli.core.credentials.oidc.detectors.buildkite import BuildkiteDetector


@pytest.fixture
def buildkite_env():
    env = {
        "BUILDKITE": "true",
        "BUILDKITE_JOB_ID": "0184990a-477b-4fa8-9968-496074483cee",
    }
    with mock.patch.dict("os.environ", env, clear=True):
        yield env


class TestDetect:
    def test_detects_when_buildkite_job_present(self, buildkite_env):
        detector = BuildkiteDetector(context=CredentialContext())
        assert detector.detect() is True

    def test_not_detected_when_unset(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            detector = BuildkiteDetector(context=CredentialContext())
            assert detector.detect() is False

    def test_not_detected_without_buildkite_flag(self, buildkite_env):
        del buildkite_env["BUILDKITE"]
        with mock.patch.dict("os.environ", buildkite_env, clear=True):
            detector = BuildkiteDetector(context=CredentialContext())
            assert detector.detect() is False

    def test_not_detected_without_job_id(self, buildkite_env):
        del buildkite_env["BUILDKITE_JOB_ID"]
        with mock.patch.dict("os.environ", buildkite_env, clear=True):
            detector = BuildkiteDetector(context=CredentialContext())
            assert detector.detect() is False


class TestGetToken:
    def test_requests_token_with_default_audience(self, buildkite_env):
        completed = subprocess.CompletedProcess([], 0, stdout="the-jwt\n", stderr="")
        with mock.patch("subprocess.run", return_value=completed) as run:
            detector = BuildkiteDetector(context=CredentialContext())

            assert detector.get_token() == "the-jwt"

        run.assert_called_once_with(
            [
                "buildkite-agent",
                "oidc",
                "request-token",
                "--audience",
                "cloudsmith",
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        )

    def test_uses_custom_audience(self, buildkite_env):
        completed = subprocess.CompletedProcess([], 0, stdout="the-jwt", stderr="")
        with mock.patch("subprocess.run", return_value=completed) as run:
            detector = BuildkiteDetector(
                context=CredentialContext(oidc_audience="custom-audience")
            )

            detector.get_token()

        assert run.call_args.args[0][-1] == "custom-audience"

    def test_raises_when_agent_returns_empty_token(self, buildkite_env):
        completed = subprocess.CompletedProcess([], 0, stdout="\n", stderr="")
        with mock.patch("subprocess.run", return_value=completed):
            detector = BuildkiteDetector(context=CredentialContext())

            with pytest.raises(ValueError, match="empty token"):
                detector.get_token()


class TestIntegration:
    def test_detect_environment_selects_buildkite(self, buildkite_env):
        detector = detect_environment(CredentialContext())
        assert isinstance(detector, BuildkiteDetector)
