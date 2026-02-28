"""Tests for the credential provider chain and OIDC auto-discovery."""

import json
import os
import stat
import time
from unittest.mock import MagicMock, patch

import pytest

from cloudsmith_cli.core.credentials import (
    CredentialContext,
    CredentialProvider,
    CredentialProviderChain,
    CredentialResult,
)
from cloudsmith_cli.core.credentials.oidc.detectors import (
    AWSDetector,
    AzureDevOpsDetector,
    BitbucketPipelinesDetector,
    CircleCIDetector,
    GenericDetector,
    GitHubActionsDetector,
    GitLabCIDetector,
    detect_environment,
)
from cloudsmith_cli.core.credentials.oidc.exchange import (
    OidcExchangeError,
    exchange_oidc_token,
)
from cloudsmith_cli.core.credentials.providers import (
    EnvironmentVariableProvider,
    OidcProvider,
)

# --- CredentialProviderChain Tests ---


class DummyProvider(CredentialProvider):
    """Test provider that returns a configurable result."""

    def __init__(self, name, result=None, should_raise=False):
        self.name = name
        self._result = result
        self._should_raise = should_raise

    def resolve(self, context):
        if self._should_raise:
            raise RuntimeError("Provider error")
        return self._result


class TestCredentialProviderChain:
    def test_first_provider_wins(self):
        result1 = CredentialResult(api_key="key1", source_name="first")
        result2 = CredentialResult(api_key="key2", source_name="second")
        chain = CredentialProviderChain(
            [
                DummyProvider("p1", result=result1),
                DummyProvider("p2", result=result2),
            ]
        )
        result = chain.resolve(CredentialContext())
        assert result.api_key == "key1"
        assert result.source_name == "first"

    def test_falls_through_to_second(self):
        result2 = CredentialResult(api_key="key2", source_name="second")
        chain = CredentialProviderChain(
            [
                DummyProvider("p1", result=None),
                DummyProvider("p2", result=result2),
            ]
        )
        result = chain.resolve(CredentialContext())
        assert result.api_key == "key2"

    def test_returns_none_when_all_fail(self):
        chain = CredentialProviderChain(
            [
                DummyProvider("p1", result=None),
                DummyProvider("p2", result=None),
            ]
        )
        result = chain.resolve(CredentialContext())
        assert result is None

    def test_skips_erroring_provider(self):
        result2 = CredentialResult(api_key="key2", source_name="second")
        chain = CredentialProviderChain(
            [
                DummyProvider("p1", should_raise=True),
                DummyProvider("p2", result=result2),
            ]
        )
        result = chain.resolve(CredentialContext())
        assert result.api_key == "key2"

    def test_empty_chain(self):
        chain = CredentialProviderChain([])
        result = chain.resolve(CredentialContext())
        assert result is None


# --- EnvironmentVariableProvider Tests ---


class TestEnvironmentVariableProvider:
    def test_resolves_from_env(self):
        provider = EnvironmentVariableProvider()
        with patch.dict(os.environ, {"CLOUDSMITH_API_KEY": "test-key-1234"}):
            result = provider.resolve(CredentialContext())
            assert result is not None
            assert result.api_key == "test-key-1234"
            assert "1234" in result.source_detail

    def test_returns_none_when_not_set(self):
        provider = EnvironmentVariableProvider()
        env = os.environ.copy()
        env.pop("CLOUDSMITH_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            result = provider.resolve(CredentialContext())
            assert result is None

    def test_returns_none_for_empty_value(self):
        provider = EnvironmentVariableProvider()
        with patch.dict(os.environ, {"CLOUDSMITH_API_KEY": "  "}):
            result = provider.resolve(CredentialContext())
            assert result is None


# --- CI/CD Detector Tests ---


class TestGitHubActionsDetector:
    def test_detects_github_actions(self):
        detector = GitHubActionsDetector()
        env = {
            "GITHUB_ACTIONS": "true",
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.example.com",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "gha-token",
        }
        with patch.dict(os.environ, env, clear=True):
            assert detector.detect() is True

    def test_not_detected_without_env(self):
        detector = GitHubActionsDetector()
        with patch.dict(os.environ, {}, clear=True):
            assert detector.detect() is False

    def test_not_detected_without_request_url(self):
        detector = GitHubActionsDetector()
        env = {
            "GITHUB_ACTIONS": "true",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "gha-token",
        }
        with patch.dict(os.environ, env, clear=True):
            assert detector.detect() is False

    @patch("cloudsmith_cli.core.credentials.oidc.detectors.github_actions.requests.get")
    def test_get_token(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"value": "jwt-token-123"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        detector = GitHubActionsDetector()
        env = {
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.example.com",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "gha-token",
        }
        with patch.dict(os.environ, env):
            token = detector.get_token()
            assert token == "jwt-token-123"

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "Bearer gha-token" in call_args.kwargs["headers"]["Authorization"]
        assert "audience=cloudsmith" in call_args.args[0]

    @patch("cloudsmith_cli.core.credentials.oidc.detectors.github_actions.requests.get")
    def test_get_token_custom_audience(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"value": "jwt-token-123"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        detector = GitHubActionsDetector()
        env = {
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.example.com",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "gha-token",
            "CLOUDSMITH_OIDC_AUDIENCE": "custom-aud",
        }
        with patch.dict(os.environ, env, clear=True):
            token = detector.get_token()
            assert token == "jwt-token-123"

        assert "audience=custom-aud" in mock_get.call_args.args[0]


class TestGitLabCIDetector:
    def test_detects_gitlab_ci(self):
        detector = GitLabCIDetector()
        env = {"GITLAB_CI": "true", "CI_JOB_JWT_V2": "gitlab-jwt"}
        with patch.dict(os.environ, env, clear=True):
            assert detector.detect() is True

    def test_not_detected_without_gitlab_ci(self):
        detector = GitLabCIDetector()
        with patch.dict(os.environ, {"CI_JOB_JWT_V2": "jwt"}, clear=True):
            assert detector.detect() is False

    def test_prefers_cloudsmith_oidc_token(self):
        detector = GitLabCIDetector()
        env = {
            "GITLAB_CI": "true",
            "CLOUDSMITH_OIDC_TOKEN": "preferred-jwt",
            "CI_JOB_JWT_V2": "fallback-jwt",
        }
        with patch.dict(os.environ, env, clear=True):
            token = detector.get_token()
            assert token == "preferred-jwt"


class TestCircleCIDetector:
    def test_detects_circleci(self):
        detector = CircleCIDetector()
        env = {"CIRCLECI": "true", "CIRCLE_OIDC_TOKEN_V2": "circle-jwt"}
        with patch.dict(os.environ, env, clear=True):
            assert detector.detect() is True

    def test_not_detected_without_token(self):
        detector = CircleCIDetector()
        env = {"CIRCLECI": "true"}
        with patch.dict(os.environ, env, clear=True):
            assert detector.detect() is False

    def test_get_token_v2(self):
        detector = CircleCIDetector()
        env = {
            "CIRCLECI": "true",
            "CIRCLE_OIDC_TOKEN_V2": "v2-jwt",
        }
        with patch.dict(os.environ, env, clear=True):
            assert detector.get_token() == "v2-jwt"


class TestAzureDevOpsDetector:
    def test_detects_azure(self):
        detector = AzureDevOpsDetector()
        env = {
            "SYSTEM_OIDCREQUESTURI": "https://oidc.example.com",
            "SYSTEM_ACCESSTOKEN": "ado-token",
        }
        with patch.dict(os.environ, env, clear=True):
            assert detector.detect() is True

    @patch("cloudsmith_cli.core.credentials.oidc.detectors.azure_devops.requests.post")
    def test_get_token(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"oidcToken": "ado-jwt-123"}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        detector = AzureDevOpsDetector()
        env = {
            "SYSTEM_OIDCREQUESTURI": "https://oidc.example.com",
            "SYSTEM_ACCESSTOKEN": "ado-token",
        }
        with patch.dict(os.environ, env):
            token = detector.get_token()
            assert token == "ado-jwt-123"

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args.kwargs["json"]["audience"] == "cloudsmith"


class TestBitbucketPipelinesDetector:
    def test_detects_bitbucket(self):
        detector = BitbucketPipelinesDetector()
        env = {"BITBUCKET_STEP_OIDC_TOKEN": "bb-jwt"}
        with patch.dict(os.environ, env, clear=True):
            assert detector.detect() is True

    def test_get_token(self):
        detector = BitbucketPipelinesDetector()
        env = {"BITBUCKET_STEP_OIDC_TOKEN": "bb-jwt-123"}
        with patch.dict(os.environ, env):
            assert detector.get_token() == "bb-jwt-123"


class TestAWSDetector:
    def test_detects_aws_with_credentials(self):
        mock_creds = MagicMock()
        mock_creds.access_key = "AKIAIOSFODNN7EXAMPLE"
        mock_frozen = MagicMock()
        mock_frozen.access_key = "AKIAIOSFODNN7EXAMPLE"
        mock_creds.get_frozen_credentials.return_value = mock_frozen
        mock_session = MagicMock()
        mock_session.get_credentials.return_value = mock_creds
        mock_boto3 = MagicMock()
        mock_boto3.Session.return_value = mock_session

        mock_botocore_exc = MagicMock()
        mock_botocore_exc.BotoCoreError = Exception
        mock_botocore_exc.ClientError = Exception
        mock_botocore_exc.NoCredentialsError = Exception

        detector = AWSDetector()
        with patch.dict(
            "sys.modules",
            {
                "boto3": mock_boto3,
                "botocore": MagicMock(),
                "botocore.exceptions": mock_botocore_exc,
            },
        ):
            assert detector.detect() is True

    def test_not_detected_without_credentials(self):
        mock_session = MagicMock()
        mock_session.get_credentials.return_value = None
        mock_boto3 = MagicMock()
        mock_boto3.Session.return_value = mock_session

        mock_botocore_exc = MagicMock()
        mock_botocore_exc.BotoCoreError = Exception
        mock_botocore_exc.ClientError = Exception
        mock_botocore_exc.NoCredentialsError = Exception

        detector = AWSDetector()
        with patch.dict(
            "sys.modules",
            {
                "boto3": mock_boto3,
                "botocore": MagicMock(),
                "botocore.exceptions": mock_botocore_exc,
            },
        ):
            assert detector.detect() is False

    def test_not_detected_without_boto3(self):
        detector = AWSDetector()
        with patch.dict("sys.modules", {"boto3": None}):
            assert detector.detect() is False

    def test_get_token(self):
        mock_sts = MagicMock()
        mock_sts.get_web_identity_token.return_value = {
            "WebIdentityToken": "aws-jwt-456",
        }
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_sts

        detector = AWSDetector()
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            assert detector.get_token() == "aws-jwt-456"

        mock_boto3.client.assert_called_once_with("sts")
        call_kwargs = mock_sts.get_web_identity_token.call_args.kwargs
        assert call_kwargs["Audience"] == ["cloudsmith"]
        assert call_kwargs["SigningAlgorithm"] == "RS256"


class TestGenericDetector:
    def test_detects_generic(self):
        detector = GenericDetector()
        env = {"CLOUDSMITH_OIDC_TOKEN": "generic-jwt"}
        with patch.dict(os.environ, env, clear=True):
            assert detector.detect() is True

    def test_get_token(self):
        detector = GenericDetector()
        env = {"CLOUDSMITH_OIDC_TOKEN": "generic-jwt-789"}
        with patch.dict(os.environ, env):
            assert detector.get_token() == "generic-jwt-789"


class TestDetectEnvironment:
    def test_returns_none_in_empty_env(self):
        with patch.dict(os.environ, {}, clear=True):
            assert detect_environment() is None

    def test_github_takes_priority(self):
        env = {
            "GITHUB_ACTIONS": "true",
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.example.com",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "gha-token",
            "CLOUDSMITH_OIDC_TOKEN": "generic-jwt",
        }
        with patch.dict(os.environ, env, clear=True):
            detector = detect_environment()
            assert detector is not None
            assert detector.name == "GitHub Actions"


# --- OIDC Exchange Tests ---


class TestOidcExchange:
    @patch("cloudsmith_cli.core.credentials.oidc.exchange.requests.post")
    def test_successful_exchange(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "cloudsmith-jwt-abc"}
        mock_post.return_value = mock_response

        token = exchange_oidc_token(
            api_host="https://api.cloudsmith.io",
            org="test-org",
            service_slug="test-service",
            oidc_token="vendor-jwt",
        )
        assert token == "cloudsmith-jwt-abc"

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args.args[0] == "https://api.cloudsmith.io/openid/test-org/"
        assert call_args.kwargs["json"]["oidc_token"] == "vendor-jwt"
        assert call_args.kwargs["json"]["service_slug"] == "test-service"

    @patch("cloudsmith_cli.core.credentials.oidc.exchange.requests.post")
    def test_4xx_raises_immediately(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"detail": "Invalid token"}
        mock_post.return_value = mock_response

        with pytest.raises(OidcExchangeError, match="401"):
            exchange_oidc_token(
                api_host="https://api.cloudsmith.io",
                org="test-org",
                service_slug="test-service",
                oidc_token="bad-jwt",
            )
        # 4xx should NOT retry
        assert mock_post.call_count == 1

    @patch("cloudsmith_cli.core.credentials.oidc.exchange.requests.post")
    def test_empty_token_raises(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": ""}
        mock_post.return_value = mock_response

        with pytest.raises(OidcExchangeError, match="empty or invalid"):
            exchange_oidc_token(
                api_host="https://api.cloudsmith.io",
                org="test-org",
                service_slug="test-service",
                oidc_token="vendor-jwt",
            )

    @patch("cloudsmith_cli.core.credentials.oidc.exchange.requests.post")
    def test_host_normalization(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "jwt-123"}
        mock_post.return_value = mock_response

        exchange_oidc_token(
            api_host="api.cloudsmith.io",
            org="myorg",
            service_slug="svc",
            oidc_token="jwt",
        )
        call_url = mock_post.call_args.args[0]
        assert call_url == "https://api.cloudsmith.io/openid/myorg/"


# --- OidcProvider Tests ---


class TestOidcProvider:
    def test_skips_without_org(self):
        provider = OidcProvider()
        env = {"CLOUDSMITH_SERVICE_SLUG": "svc"}
        with patch.dict(os.environ, env, clear=True):
            result = provider.resolve(CredentialContext(debug=True))
            assert result is None

    def test_skips_without_service_slug(self):
        provider = OidcProvider()
        env = {"CLOUDSMITH_ORG": "myorg"}
        with patch.dict(os.environ, env, clear=True):
            result = provider.resolve(CredentialContext(debug=True))
            assert result is None

    @patch("cloudsmith_cli.core.credentials.oidc.exchange.exchange_oidc_token")
    @patch("cloudsmith_cli.core.credentials.oidc.detectors.detect_environment")
    def test_resolves_oidc(self, mock_detect, mock_exchange):
        mock_detector = MagicMock()
        mock_detector.name = "GitHub Actions"
        mock_detector.get_token.return_value = "vendor-jwt"
        mock_detect.return_value = mock_detector
        mock_exchange.return_value = "cloudsmith-jwt-xyz"

        provider = OidcProvider()
        env = {
            "CLOUDSMITH_ORG": "myorg",
            "CLOUDSMITH_SERVICE_SLUG": "mysvc",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "cloudsmith_cli.core.credentials.oidc.cache.get_cached_token",
            return_value=None,
        ), patch(
            "cloudsmith_cli.core.credentials.oidc.cache.store_cached_token",
        ):
            result = provider.resolve(
                CredentialContext(api_host="https://api.cloudsmith.io")
            )
            assert result is not None
            assert result.api_key == "cloudsmith-jwt-xyz"
            assert result.source_name == "oidc"
            assert "GitHub Actions" in result.source_detail
            assert "myorg" in result.source_detail

    @patch("cloudsmith_cli.core.credentials.oidc.detectors.detect_environment")
    def test_returns_none_when_no_env_detected(self, mock_detect):
        mock_detect.return_value = None

        provider = OidcProvider()
        env = {
            "CLOUDSMITH_ORG": "myorg",
            "CLOUDSMITH_SERVICE_SLUG": "mysvc",
        }
        with patch.dict(os.environ, env, clear=True):
            result = provider.resolve(CredentialContext())
            assert result is None

    @patch("cloudsmith_cli.core.credentials.oidc.exchange.exchange_oidc_token")
    @patch("cloudsmith_cli.core.credentials.oidc.detectors.detect_environment")
    def test_returns_none_on_exchange_failure(self, mock_detect, mock_exchange):
        mock_detector = MagicMock()
        mock_detector.name = "CircleCI"
        mock_detector.get_token.return_value = "vendor-jwt"
        mock_detect.return_value = mock_detector
        mock_exchange.side_effect = OidcExchangeError("exchange failed")

        provider = OidcProvider()
        env = {
            "CLOUDSMITH_ORG": "myorg",
            "CLOUDSMITH_SERVICE_SLUG": "mysvc",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "cloudsmith_cli.core.credentials.oidc.cache.get_cached_token",
            return_value=None,
        ):
            result = provider.resolve(CredentialContext())
            assert result is None


# --- Integration: Chain Priority Tests ---


class TestChainPriority:
    """Verify that earlier providers take priority over OIDC."""

    def test_env_var_beats_oidc(self):
        env_provider = EnvironmentVariableProvider()
        oidc_provider = OidcProvider()

        chain = CredentialProviderChain([env_provider, oidc_provider])

        env = {
            "CLOUDSMITH_API_KEY": "my-api-key",
            "CLOUDSMITH_ORG": "myorg",
            "CLOUDSMITH_SERVICE_SLUG": "mysvc",
            "CLOUDSMITH_OIDC_TOKEN": "generic-jwt",
        }
        with patch.dict(os.environ, env, clear=True):
            result = chain.resolve(CredentialContext())
            assert result is not None
            assert result.api_key == "my-api-key"
            assert result.source_name == "environment_variable"

    @patch("cloudsmith_cli.core.credentials.oidc.exchange.exchange_oidc_token")
    @patch("cloudsmith_cli.core.credentials.oidc.detectors.detect_environment")
    def test_oidc_used_as_fallback(self, mock_detect, mock_exchange):
        mock_detector = MagicMock()
        mock_detector.name = "Generic (CLOUDSMITH_OIDC_TOKEN)"
        mock_detector.get_token.return_value = "vendor-jwt"
        mock_detect.return_value = mock_detector
        mock_exchange.return_value = "cloudsmith-jwt"

        env_provider = EnvironmentVariableProvider()
        oidc_provider = OidcProvider()

        chain = CredentialProviderChain([env_provider, oidc_provider])

        env = {
            "CLOUDSMITH_ORG": "myorg",
            "CLOUDSMITH_SERVICE_SLUG": "mysvc",
            "CLOUDSMITH_OIDC_TOKEN": "generic-jwt",
        }
        # Ensure CLOUDSMITH_API_KEY is NOT set
        clean_env = {k: v for k, v in env.items()}
        with patch.dict(os.environ, clean_env, clear=True), patch(
            "cloudsmith_cli.core.credentials.oidc.cache.get_cached_token",
            return_value=None,
        ), patch(
            "cloudsmith_cli.core.credentials.oidc.cache.store_cached_token",
        ):
            result = chain.resolve(
                CredentialContext(api_host="https://api.cloudsmith.io")
            )
            assert result is not None
            assert result.api_key == "cloudsmith-jwt"
            assert result.source_name == "oidc"


# =============================================================================
# OIDC Token Cache Tests
# =============================================================================


class TestOidcTokenCache:
    """Tests for OIDC token filesystem caching."""

    def _make_jwt(self, exp=None):
        """Create a minimal JWT with an optional exp claim."""
        import base64

        header = (
            base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode())
            .rstrip(b"=")
            .decode()
        )
        payload_data = {}
        if exp is not None:
            payload_data["exp"] = exp
        payload = (
            base64.urlsafe_b64encode(json.dumps(payload_data).encode())
            .rstrip(b"=")
            .decode()
        )
        sig = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=").decode()
        return f"{header}.{payload}.{sig}"

    def test_cache_roundtrip(self, tmp_path):
        """Store and retrieve a cached token."""
        from cloudsmith_cli.core.credentials.oidc.cache import (
            get_cached_token,
            store_cached_token,
        )

        future_exp = time.time() + 3600
        token = self._make_jwt(exp=future_exp)

        with patch(
            "cloudsmith_cli.core.credentials.oidc.cache._get_cache_dir",
            return_value=str(tmp_path),
        ):
            store_cached_token("https://api.cloudsmith.io", "org", "svc", token)
            result = get_cached_token("https://api.cloudsmith.io", "org", "svc")
            assert result == token

    def test_expired_token_not_returned(self, tmp_path):
        """An expired token should not be returned from cache."""
        from cloudsmith_cli.core.credentials.oidc.cache import (
            get_cached_token,
            store_cached_token,
        )

        past_exp = time.time() - 100
        token = self._make_jwt(exp=past_exp)

        with patch(
            "cloudsmith_cli.core.credentials.oidc.cache._get_cache_dir",
            return_value=str(tmp_path),
        ):
            store_cached_token("https://api.cloudsmith.io", "org", "svc", token)
            result = get_cached_token("https://api.cloudsmith.io", "org", "svc")
            assert result is None

    def test_expiring_soon_token_not_returned(self, tmp_path):
        """A token expiring within the margin should not be returned."""
        from cloudsmith_cli.core.credentials.oidc.cache import (
            get_cached_token,
            store_cached_token,
        )

        # Expires in 30s but margin is 60s
        exp = time.time() + 30
        token = self._make_jwt(exp=exp)

        with patch(
            "cloudsmith_cli.core.credentials.oidc.cache._get_cache_dir",
            return_value=str(tmp_path),
        ):
            store_cached_token("https://api.cloudsmith.io", "org", "svc", token)
            result = get_cached_token("https://api.cloudsmith.io", "org", "svc")
            assert result is None

    def test_no_cache_file_returns_none(self, tmp_path):
        """Missing cache file returns None."""
        from cloudsmith_cli.core.credentials.oidc.cache import get_cached_token

        with patch(
            "cloudsmith_cli.core.credentials.oidc.cache._get_cache_dir",
            return_value=str(tmp_path),
        ):
            result = get_cached_token("https://api.cloudsmith.io", "org", "svc")
            assert result is None

    def test_different_keys_are_independent(self, tmp_path):
        """Tokens for different org/service combos are cached separately."""
        from cloudsmith_cli.core.credentials.oidc.cache import (
            get_cached_token,
            store_cached_token,
        )

        future_exp = time.time() + 3600
        token_a = self._make_jwt(exp=future_exp)
        token_b = self._make_jwt(exp=future_exp)

        with patch(
            "cloudsmith_cli.core.credentials.oidc.cache._get_cache_dir",
            return_value=str(tmp_path),
        ):
            store_cached_token("https://api.cloudsmith.io", "org-a", "svc", token_a)
            store_cached_token("https://api.cloudsmith.io", "org-b", "svc", token_b)
            assert (
                get_cached_token("https://api.cloudsmith.io", "org-a", "svc") == token_a
            )
            assert (
                get_cached_token("https://api.cloudsmith.io", "org-b", "svc") == token_b
            )

    def test_invalidate_cached_token(self, tmp_path):
        """invalidate_cached_token removes the cache file."""
        from cloudsmith_cli.core.credentials.oidc.cache import (
            get_cached_token,
            invalidate_cached_token,
            store_cached_token,
        )

        future_exp = time.time() + 3600
        token = self._make_jwt(exp=future_exp)

        with patch(
            "cloudsmith_cli.core.credentials.oidc.cache._get_cache_dir",
            return_value=str(tmp_path),
        ):
            store_cached_token("https://api.cloudsmith.io", "org", "svc", token)
            assert (
                get_cached_token("https://api.cloudsmith.io", "org", "svc") is not None
            )
            invalidate_cached_token("https://api.cloudsmith.io", "org", "svc")
            assert get_cached_token("https://api.cloudsmith.io", "org", "svc") is None

    def test_corrupt_cache_file_returns_none(self, tmp_path):
        """A corrupted cache file should be handled gracefully."""
        from cloudsmith_cli.core.credentials.oidc.cache import (
            _cache_key,
            get_cached_token,
        )

        cache_file = tmp_path / _cache_key("https://api.cloudsmith.io", "org", "svc")
        cache_file.write_text("not valid json{{{")

        with patch(
            "cloudsmith_cli.core.credentials.oidc.cache._get_cache_dir",
            return_value=str(tmp_path),
        ):
            result = get_cached_token("https://api.cloudsmith.io", "org", "svc")
            assert result is None

    def test_token_without_exp_is_cached(self, tmp_path):
        """A token with no exp claim should still be cached and returned."""
        from cloudsmith_cli.core.credentials.oidc.cache import (
            get_cached_token,
            store_cached_token,
        )

        token = self._make_jwt(exp=None)

        with patch(
            "cloudsmith_cli.core.credentials.oidc.cache._get_cache_dir",
            return_value=str(tmp_path),
        ):
            store_cached_token("https://api.cloudsmith.io", "org", "svc", token)
            result = get_cached_token("https://api.cloudsmith.io", "org", "svc")
            assert result == token

    def test_cache_file_permissions(self, tmp_path):
        """Cache files should be created with restricted permissions (0600)."""
        from cloudsmith_cli.core.credentials.oidc.cache import (
            _cache_key,
            store_cached_token,
        )

        future_exp = time.time() + 3600
        token = self._make_jwt(exp=future_exp)

        # Mock keyring to be unavailable so disk cache is used
        with patch(
            "cloudsmith_cli.core.credentials.oidc.cache._get_cache_dir",
            return_value=str(tmp_path),
        ), patch("cloudsmith_cli.core.keyring.should_use_keyring", return_value=False):
            store_cached_token("https://api.cloudsmith.io", "org", "svc", token)
            cache_file = tmp_path / _cache_key(
                "https://api.cloudsmith.io", "org", "svc"
            )
            mode = cache_file.stat().st_mode
            assert stat.S_IMODE(mode) == 0o600

    @patch("cloudsmith_cli.core.credentials.oidc.exchange.exchange_oidc_token")
    @patch("cloudsmith_cli.core.credentials.oidc.detectors.detect_environment")
    def test_oidc_provider_uses_cache(self, mock_detect, mock_exchange, tmp_path):
        """OidcProvider should use cached token instead of re-exchanging."""
        from cloudsmith_cli.core.credentials.oidc.cache import store_cached_token

        future_exp = time.time() + 3600
        cached_token = self._make_jwt(exp=future_exp)

        mock_detector = MagicMock()
        mock_detector.name = "GitHub Actions"
        mock_detector.get_token.return_value = "vendor-jwt"
        mock_detect.return_value = mock_detector

        env = {
            "CLOUDSMITH_ORG": "myorg",
            "CLOUDSMITH_SERVICE_SLUG": "mysvc",
        }

        with patch(
            "cloudsmith_cli.core.credentials.oidc.cache._get_cache_dir",
            return_value=str(tmp_path),
        ), patch.dict(os.environ, env, clear=True):
            store_cached_token(
                "https://api.cloudsmith.io", "myorg", "mysvc", cached_token
            )

            provider = OidcProvider()
            result = provider.resolve(
                CredentialContext(api_host="https://api.cloudsmith.io")
            )

            assert result is not None
            assert result.api_key == cached_token
            assert "[cached]" in result.source_detail
            # exchange should NOT have been called
            mock_exchange.assert_not_called()

    @patch("cloudsmith_cli.core.credentials.oidc.exchange.exchange_oidc_token")
    @patch("cloudsmith_cli.core.credentials.oidc.detectors.detect_environment")
    def test_oidc_provider_exchanges_when_cache_expired(
        self, mock_detect, mock_exchange, tmp_path
    ):
        """OidcProvider should exchange when cached token is expired."""
        from cloudsmith_cli.core.credentials.oidc.cache import store_cached_token

        expired_token = self._make_jwt(exp=time.time() - 100)
        fresh_token = "fresh-cloudsmith-jwt"

        mock_detector = MagicMock()
        mock_detector.name = "GitHub Actions"
        mock_detector.get_token.return_value = "vendor-jwt"
        mock_detect.return_value = mock_detector
        mock_exchange.return_value = fresh_token

        env = {
            "CLOUDSMITH_ORG": "myorg",
            "CLOUDSMITH_SERVICE_SLUG": "mysvc",
        }

        with patch(
            "cloudsmith_cli.core.credentials.oidc.cache._get_cache_dir",
            return_value=str(tmp_path),
        ), patch.dict(os.environ, env, clear=True):
            store_cached_token(
                "https://api.cloudsmith.io", "myorg", "mysvc", expired_token
            )

            provider = OidcProvider()
            result = provider.resolve(
                CredentialContext(api_host="https://api.cloudsmith.io")
            )

            assert result is not None
            assert result.api_key == fresh_token
            assert "[cached]" not in result.source_detail
            mock_exchange.assert_called_once()

    def test_keyring_storage_with_fallback(self, tmp_path):
        """OIDC tokens should use keyring when available, skip disk when keyring works."""
        from cloudsmith_cli.core.credentials.oidc.cache import store_cached_token

        future_exp = time.time() + 3600
        token = self._make_jwt(exp=future_exp)

        # Mock keyring to succeed
        with patch(
            "cloudsmith_cli.core.credentials.oidc.cache._get_cache_dir",
            return_value=str(tmp_path),
        ), patch(
            "cloudsmith_cli.core.keyring.should_use_keyring", return_value=True
        ), patch(
            "cloudsmith_cli.core.keyring.store_oidc_token", return_value=True
        ) as mock_keyring_store:
            store_cached_token("https://api.cloudsmith.io", "org", "svc", token)

            # Keyring storage should have been attempted
            mock_keyring_store.assert_called_once()

            # Disk storage should NOT happen when keyring succeeds
            cache_files = list(tmp_path.glob("oidc_*.json"))
            assert len(cache_files) == 0

    def test_keyring_failure_falls_back_to_disk(self, tmp_path):
        """When keyring fails, should fall back to disk storage."""
        from cloudsmith_cli.core.credentials.oidc.cache import store_cached_token

        future_exp = time.time() + 3600
        token = self._make_jwt(exp=future_exp)

        # Mock keyring to fail
        with patch(
            "cloudsmith_cli.core.credentials.oidc.cache._get_cache_dir",
            return_value=str(tmp_path),
        ), patch(
            "cloudsmith_cli.core.keyring.should_use_keyring", return_value=True
        ), patch(
            "cloudsmith_cli.core.keyring.store_oidc_token", return_value=False
        ) as mock_keyring_store:
            store_cached_token("https://api.cloudsmith.io", "org", "svc", token)

            # Keyring storage should have been attempted
            mock_keyring_store.assert_called_once()

            # Disk storage SHOULD happen when keyring fails
            cache_files = list(tmp_path.glob("oidc_*.json"))
            assert len(cache_files) == 1

    def test_keyring_retrieval_priority(self, tmp_path):
        """Keyring should be checked before disk cache."""
        from cloudsmith_cli.core.credentials.oidc.cache import get_cached_token

        future_exp = time.time() + 3600
        keyring_token = self._make_jwt(exp=future_exp)

        token_data = json.dumps(
            {
                "token": keyring_token,
                "expires_at": future_exp,
                "api_host": "https://api.cloudsmith.io",
                "org": "org",
                "service_slug": "svc",
                "cached_at": time.time(),
            }
        )

        # Mock keyring to return a token
        with patch(
            "cloudsmith_cli.core.credentials.oidc.cache._get_cache_dir",
            return_value=str(tmp_path),
        ), patch("cloudsmith_cli.core.keyring.get_oidc_token", return_value=token_data):
            result = get_cached_token("https://api.cloudsmith.io", "org", "svc")

            # Should get the keyring token (disk cache not even checked)
            assert result == keyring_token

    def test_keyring_disabled_uses_disk(self, tmp_path):
        """When keyring is disabled, should use disk cache only."""
        from cloudsmith_cli.core.credentials.oidc.cache import (
            get_cached_token,
            store_cached_token,
        )

        future_exp = time.time() + 3600
        token = self._make_jwt(exp=future_exp)

        # Mock CLOUDSMITH_NO_KEYRING=1
        with patch(
            "cloudsmith_cli.core.credentials.oidc.cache._get_cache_dir",
            return_value=str(tmp_path),
        ), patch("cloudsmith_cli.core.keyring.should_use_keyring", return_value=False):
            store_cached_token("https://api.cloudsmith.io", "org", "svc", token)
            result = get_cached_token("https://api.cloudsmith.io", "org", "svc")

            # Should successfully use disk cache
            assert result == token

            # Verify disk file was created
            cache_files = list(tmp_path.glob("oidc_*.json"))
            assert len(cache_files) == 1
