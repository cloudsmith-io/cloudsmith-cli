"""Tests for the Google Cloud OIDC detector."""

import sys
from unittest import mock

import pytest

from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.oidc.detectors.gcp import GCPDetector

compute_engine = pytest.importorskip("google.auth.compute_engine")
exceptions = pytest.importorskip("google.auth.exceptions")
oauth2_creds = pytest.importorskip("google.oauth2.credentials")

METADATA_GET = "google.auth.compute_engine._metadata.get"
METADATA_IS_ON_GCE = "google.auth.compute_engine._metadata.is_on_gce"
FETCH_ID_TOKEN_CREDS = "google.oauth2.id_token.fetch_id_token_credentials"


def make_detector(**ctx):
    return GCPDetector(context=CredentialContext(**ctx))


class TestDetect:
    def test_not_detected_when_google_auth_missing(self):
        with mock.patch.dict(sys.modules, {"google.auth": None}):
            assert make_detector().detect() is False

    def test_detected_when_adc_resolves(self):
        with mock.patch("google.auth.default", return_value=(mock.MagicMock(), "proj")):
            assert make_detector().detect() is True

    def test_detected_via_metadata_when_adc_unavailable(self):
        with mock.patch(
            "google.auth.default",
            side_effect=exceptions.DefaultCredentialsError("no adc"),
        ), mock.patch(METADATA_IS_ON_GCE, return_value=True):
            assert make_detector().detect() is True

    def test_not_detected_when_nothing_available(self):
        with mock.patch(
            "google.auth.default",
            side_effect=exceptions.DefaultCredentialsError("no adc"),
        ), mock.patch(METADATA_IS_ON_GCE, return_value=False):
            assert make_detector().detect() is False

    def test_not_detected_on_google_auth_error(self):
        with mock.patch(
            "google.auth.default", side_effect=exceptions.GoogleAuthError("boom")
        ):
            assert make_detector().detect() is False


class TestGetTokenMetadata:
    def test_compute_credentials_use_metadata_with_format_full(self):
        compute_creds = mock.Mock(spec=compute_engine.Credentials)
        with mock.patch(
            "google.auth.default", return_value=(compute_creds, "proj")
        ), mock.patch(METADATA_GET, return_value="meta-jwt\n") as get:
            token = make_detector().get_token()
        assert token == "meta-jwt"
        args, kwargs = get.call_args
        assert args[1] == "instance/service-accounts/default/identity"
        assert kwargs["params"] == {"audience": "cloudsmith", "format": "full"}

    def test_uses_configured_audience(self):
        compute_creds = mock.Mock(spec=compute_engine.Credentials)
        with mock.patch(
            "google.auth.default", return_value=(compute_creds, "proj")
        ), mock.patch(METADATA_GET, return_value="meta-jwt") as get:
            make_detector(oidc_audience="custom-aud").get_token()
        _, kwargs = get.call_args
        assert kwargs["params"]["audience"] == "custom-aud"

    def test_falls_back_to_metadata_when_default_raises(self):
        with mock.patch(
            "google.auth.default",
            side_effect=exceptions.DefaultCredentialsError("no adc"),
        ), mock.patch(METADATA_GET, return_value="meta-jwt"):
            assert make_detector().get_token() == "meta-jwt"

    def test_raises_when_metadata_returns_blank(self):
        compute_creds = mock.Mock(spec=compute_engine.Credentials)
        with mock.patch(
            "google.auth.default", return_value=(compute_creds, "proj")
        ), mock.patch(METADATA_GET, return_value="   "):
            with pytest.raises(ValueError):
                make_detector().get_token()

    def test_raises_when_metadata_errors(self):
        compute_creds = mock.Mock(spec=compute_engine.Credentials)
        with mock.patch(
            "google.auth.default", return_value=(compute_creds, "proj")
        ), mock.patch(METADATA_GET, side_effect=exceptions.TransportError("boom")):
            with pytest.raises(ValueError):
                make_detector().get_token()


class TestGetTokenUserCredentials:
    def test_returns_refreshed_id_token(self):
        user_creds = mock.Mock(spec=oauth2_creds.Credentials)
        user_creds.id_token = "adc-jwt"
        with mock.patch("google.auth.default", return_value=(user_creds, "proj")):
            token = make_detector().get_token()
        assert token == "adc-jwt"
        user_creds.refresh.assert_called_once()

    def test_raises_when_user_credentials_have_no_id_token(self):
        user_creds = mock.Mock(spec=oauth2_creds.Credentials)
        user_creds.id_token = None
        with mock.patch("google.auth.default", return_value=(user_creds, "proj")):
            with pytest.raises(ValueError):
                make_detector().get_token()


class TestGetTokenIdTokenCredentials:
    def test_delegates_to_fetch_id_token_credentials(self):
        # A non-compute, non-user credential (e.g. service-account key or
        # Workload Identity Federation) is delegated to google-auth's dispatch.
        other_creds = mock.Mock()
        id_creds = mock.Mock(token="sa-jwt")
        with mock.patch(
            "google.auth.default", return_value=(other_creds, "proj")
        ), mock.patch(FETCH_ID_TOKEN_CREDS, return_value=id_creds) as fetch:
            token = make_detector(oidc_audience="aud").get_token()
        assert token == "sa-jwt"
        args, _ = fetch.call_args
        assert args[0] == "aud"
        id_creds.refresh.assert_called_once()

    def test_raises_when_dispatch_fails(self):
        other_creds = mock.Mock()
        with mock.patch(
            "google.auth.default", return_value=(other_creds, "proj")
        ), mock.patch(
            FETCH_ID_TOKEN_CREDS, side_effect=exceptions.DefaultCredentialsError("x")
        ):
            with pytest.raises(ValueError):
                make_detector().get_token()


class TestRegistration:
    def test_registered_after_aws(self):
        from cloudsmith_cli.core.credentials.oidc.detectors import (
            _DETECTORS,
            AWSDetector,
        )

        assert _DETECTORS.index(GCPDetector) == _DETECTORS.index(AWSDetector) + 1
