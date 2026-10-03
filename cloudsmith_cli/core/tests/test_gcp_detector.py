# Copyright 2026 Cloudsmith Ltd
"""Tests for Google Cloud discovery and ID-token generation using the real SDK."""

import json
import sys
from unittest import mock
from urllib.parse import parse_qs

import httpretty
import jwt
import pytest
from google.auth import compute_engine, exceptions, impersonated_credentials
from google.oauth2 import credentials as user_creds
from google.oauth2 import service_account

from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.oidc.detectors import (
    AWSDetector,
    detect_environment,
    disabled_detectors_from_env,
    registered_detectors,
)
from cloudsmith_cli.core.credentials.oidc.detectors.gcp import GCPDetector
from cloudsmith_cli.core.credentials.providers.oidc_provider import OidcProvider

METADATA_GET = "google.auth.compute_engine._metadata.get"
TOKEN_URI = "https://oauth2.googleapis.com/token"
EMAIL = "builder@example.iam.gserviceaccount.com"
IAM_URL = f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{EMAIL}:generateIdToken"


def make_detector(**ctx):
    return GCPDetector(context=CredentialContext(**ctx))


def make_token(audience="cloudsmith"):
    return jwt.encode(
        {"aud": audience, "iss": "https://accounts.google.com", "exp": 2000000000},
        key="",
        algorithm="none",
    )


def service_credentials():
    signer = mock.Mock()
    signer.key_id = "test-key"
    signer.sign.return_value = b"test-signature"
    return service_account.Credentials(signer, EMAIL, TOKEN_URI)


class TestDetect:
    def test_not_detected_when_google_auth_missing(self):
        with mock.patch.dict(sys.modules, {"google.auth": None}):
            assert make_detector().detect() is False

    @pytest.mark.parametrize(
        "error",
        [
            exceptions.DefaultCredentialsError("invalid ADC"),
            exceptions.TransportError("unreachable"),
        ],
    )
    def test_not_detected_on_google_auth_error(self, error):
        with (
            mock.patch("google.auth.default", side_effect=error),
            mock.patch(METADATA_GET) as metadata,
        ):
            assert make_detector().detect() is False
        metadata.assert_not_called()

    def test_unsupported_adc_does_not_shadow_generic_detector(self, monkeypatch):
        monkeypatch.setenv("CLOUDSMITH_OIDC_TOKEN", "generic-token")
        with mock.patch("google.auth.default", return_value=(mock.Mock(), "proj")):
            detector = detect_environment(
                CredentialContext(oidc_detector_order="gcp,generic")
            )
        assert detector is not None
        assert detector.id == "generic"


class TestGetTokenMetadata:
    @pytest.mark.parametrize("audience", [None, "custom-audience"])
    def test_uses_detected_credentials_and_requests_full_token(self, audience):
        with (
            mock.patch(
                "google.auth.default",
                return_value=(compute_engine.Credentials(), "proj"),
            ) as default,
            mock.patch(METADATA_GET, return_value="meta-jwt\n") as get,
        ):
            detector = make_detector(oidc_audience=audience)
            assert detector.detect()
            assert detector.get_token() == "meta-jwt"
        default.assert_called_once()
        assert get.call_args.args[1] == "instance/service-accounts/default/identity"
        assert get.call_args.kwargs["params"] == {
            "audience": audience or "cloudsmith",
            "format": "full",
        }

    @pytest.mark.parametrize("token", ["", "  ", None, {"token": "unexpected-json"}])
    def test_rejects_empty_or_invalid_metadata_token(self, token):
        with (
            mock.patch(
                "google.auth.default",
                return_value=(compute_engine.Credentials(), None),
            ),
            mock.patch(METADATA_GET, return_value=token),
            pytest.raises(ValueError, match="could not mint"),
        ):
            make_detector().get_token()

    @pytest.mark.parametrize("status", [None, 403, 500])
    def test_does_not_fall_back_on_metadata_failure(self, status):
        error = exceptions.TransportError("metadata failed", mock.Mock(status=status))
        with (
            mock.patch(
                "google.auth.default",
                return_value=(compute_engine.Credentials(), None),
            ),
            mock.patch(METADATA_GET, side_effect=error) as get,
            pytest.raises(exceptions.TransportError),
        ):
            make_detector().get_token()
        get.assert_called_once()

    @httpretty.activate
    def test_cloud_build_missing_identity_endpoint_uses_iam(self, monkeypatch):
        # Newer google-auth starts an unrelated background policy lookup after
        # refreshing compute credentials; keep this token-flow test synchronous.
        monkeypatch.setattr(
            compute_engine.Credentials,
            "_is_regional_access_boundary_lookup_required",
            lambda self: False,
            raising=False,
        )
        metadata = "http://metadata.google.internal/computeMetadata/v1/"
        httpretty.register_uri(
            httpretty.GET,
            metadata + "universe/universe-domain",
            body="googleapis.com",
            content_type="text/plain",
        )
        httpretty.register_uri(
            httpretty.GET,
            metadata + "instance/service-accounts/default/identity",
            status=404,
        )
        httpretty.register_uri(
            httpretty.GET,
            metadata + "instance/service-accounts/default/email",
            body=EMAIL,
            content_type="text/plain",
        )
        httpretty.register_uri(
            httpretty.GET,
            metadata + "instance/service-accounts/default/",
            body=json.dumps({"email": EMAIL, "scopes": []}),
            content_type="application/json",
        )
        for account in ("default", EMAIL):
            httpretty.register_uri(
                httpretty.GET,
                metadata + f"instance/service-accounts/{account}/token",
                body=json.dumps(
                    {"access_token": "metadata-access-token", "expires_in": 3600}
                ),
                content_type="application/json",
            )
        httpretty.register_uri(
            httpretty.POST,
            IAM_URL,
            body=json.dumps({"token": make_token("custom-audience")}),
            content_type="application/json",
        )
        with mock.patch(
            "google.auth.default", return_value=(compute_engine.Credentials(), None)
        ):
            assert make_detector(
                oidc_audience="custom-audience"
            ).get_token() == make_token("custom-audience")
        request = httpretty.last_request()
        assert request.headers["Authorization"] == "Bearer metadata-access-token"
        assert json.loads(request.body) == {
            "audience": "custom-audience",
            "includeEmail": True,
            "delegates": None,
        }


class TestGetTokenUserCredentials:
    @pytest.mark.parametrize("audience", ["cloudsmith", "oauth-client-id"])
    def test_does_not_silently_ignore_requested_audience(self, audience):
        credentials = mock.Mock(spec=user_creds.Credentials)
        credentials.id_token = make_token("oauth-client-id")
        with mock.patch("google.auth.default", return_value=(credentials, None)):
            detector = make_detector(oidc_audience=audience)
            assert detector.detect()
            if audience == "oauth-client-id":
                assert detector.get_token() == credentials.id_token
            else:
                with pytest.raises(ValueError, match="OAuth client ID"):
                    detector.get_token()
        credentials.refresh.assert_called_once()

    def test_rejects_missing_user_id_token(self):
        credentials = mock.Mock(spec=user_creds.Credentials)
        credentials.id_token = None
        with (
            mock.patch("google.auth.default", return_value=(credentials, None)),
            pytest.raises(ValueError, match="could not mint"),
        ):
            make_detector().get_token()

    def test_refresh_error_is_preserved(self):
        credentials = mock.Mock(spec=user_creds.Credentials)
        credentials.refresh.side_effect = exceptions.RefreshError("reauthenticate")
        with (
            mock.patch("google.auth.default", return_value=(credentials, None)),
            pytest.raises(exceptions.RefreshError, match="reauthenticate"),
        ):
            make_detector().get_token()


class TestGetTokenServiceAccount:
    @httpretty.activate
    def test_impersonated_adc_preserves_target_audience_and_delegates(
        self, tmp_path, monkeypatch
    ):
        delegates = ["delegate@example.iam.gserviceaccount.com"]
        credentials_file = tmp_path / "adc.json"
        credentials_file.write_text(
            json.dumps(
                {
                    "type": "impersonated_service_account",
                    "service_account_impersonation_url": IAM_URL.replace(
                        ":generateIdToken", ":generateAccessToken"
                    ),
                    "source_credentials": {
                        "type": "authorized_user",
                        "client_id": "test-client-id",
                        "client_secret": "test-client-secret",
                        "refresh_token": "test-refresh-token",
                    },
                    "delegates": delegates,
                }
            )
        )
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(credentials_file))
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
        httpretty.register_uri(
            httpretty.POST,
            TOKEN_URI,
            body=json.dumps(
                {"access_token": "source-access-token", "expires_in": 3600}
            ),
            content_type="application/json",
        )
        httpretty.register_uri(
            httpretty.POST,
            IAM_URL,
            body=json.dumps({"token": make_token("custom-audience")}),
            content_type="application/json",
        )
        detector = make_detector(oidc_audience="custom-audience")
        assert detector.detect()
        assert detector.get_token() == make_token("custom-audience")
        request = httpretty.last_request()
        assert request.headers["Authorization"] == "Bearer source-access-token"
        assert json.loads(request.body) == {
            "audience": "custom-audience",
            "includeEmail": True,
            "delegates": delegates,
        }

    @httpretty.activate
    def test_resolved_key_credentials_work_without_rediscovering_adc(self):
        httpretty.register_uri(
            httpretty.POST,
            TOKEN_URI,
            body=json.dumps({"id_token": make_token("custom-audience")}),
            content_type="application/json",
        )
        with (
            mock.patch(
                "google.auth.default", return_value=(service_credentials(), "proj")
            ) as default,
            mock.patch.dict("os.environ", {}, clear=True),
        ):
            detector = make_detector(oidc_audience="custom-audience")
            assert detector.detect()
            assert detector.get_token() == make_token("custom-audience")
        default.assert_called_once()
        assertion = parse_qs(httpretty.last_request().body.decode())["assertion"][0]
        claims = jwt.decode(assertion, options={"verify_signature": False})
        assert claims["target_audience"] == "custom-audience"
        assert claims["iss"] == EMAIL

    @httpretty.activate
    def test_iam_permission_failure_is_preserved(self):
        credentials = impersonated_credentials.Credentials(
            source_credentials=user_creds.Credentials(token="source-access-token"),
            target_principal=EMAIL,
            target_scopes=[],
        )
        httpretty.register_uri(
            httpretty.POST,
            IAM_URL,
            status=403,
            body=json.dumps({"error": "permission denied"}),
            content_type="application/json",
        )
        with (
            mock.patch("google.auth.default", return_value=(credentials, None)),
            pytest.raises(exceptions.RefreshError, match="permission denied"),
        ):
            make_detector().get_token()


class TestRegistration:
    def test_unsupported_credentials_cannot_be_used_directly(self):
        with (
            mock.patch("google.auth.default", return_value=(mock.Mock(), None)),
            pytest.raises(TypeError, match="cannot mint an OIDC ID token"),
        ):
            make_detector().get_token()

    def test_registered_after_aws(self):
        detectors = registered_detectors()
        assert detectors.index(GCPDetector) == detectors.index(AWSDetector) + 1

    def test_disabled_gcp_does_not_resolve_adc(self):
        with mock.patch("google.auth.default") as default:
            assert (
                detect_environment(
                    CredentialContext(
                        oidc_detector_order="gcp",
                        oidc_disabled_detectors=disabled_detectors_from_env(
                            {"CLOUDSMITH_OIDC_GCP_DISABLED": "true"}
                        ),
                    )
                )
                is None
            )
        default.assert_not_called()

    def test_missing_dependency_reports_install_extra(self):
        with (
            mock.patch.dict(sys.modules, {"google.auth": None}),
            pytest.raises(ValueError, match=r"cloudsmith-cli\[gcp\]"),
        ):
            make_detector().get_token()

    def test_gcp_token_reaches_cloudsmith_exchange(self):
        context = CredentialContext(
            org="test-org", oidc_service_slug="test-service", oidc_detector_order="gcp"
        )
        with (
            mock.patch(
                "google.auth.default", return_value=(compute_engine.Credentials(), None)
            ),
            mock.patch(METADATA_GET, return_value=make_token()),
            mock.patch(
                "cloudsmith_cli.core.credentials.oidc.cache.get_cached_token",
                return_value=None,
            ),
            mock.patch("cloudsmith_cli.core.credentials.oidc.cache.store_cached_token"),
            mock.patch(
                "cloudsmith_cli.core.credentials.oidc.exchange.exchange_oidc_token",
                return_value="exchanged-token",
            ) as exchange,
        ):
            result = OidcProvider().resolve(context)
        exchange.assert_called_once_with(
            context=context,
            org="test-org",
            service_slug="test-service",
            oidc_token=make_token(),
        )
        assert result is not None
        assert result.api_key == "exchanged-token"
