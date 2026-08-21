"""Tests for the AWS OIDC detector."""

import os
from unittest import mock

import pytest

from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.oidc.detectors.aws import (
    AWSDetector,
    _resolve_region,
)

boto3 = pytest.importorskip("boto3")
MetadataRetrievalError = pytest.importorskip(
    "botocore.exceptions"
).MetadataRetrievalError
BadIMDSRequestError = pytest.importorskip("botocore.utils").BadIMDSRequestError

ISOLATED_AWS_ENV = {
    "AWS_CONFIG_FILE": os.devnull,
    "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
}


def _aws_env(**overrides):
    """Return an env dict that hides the host's AWS config files."""
    return {**ISOLATED_AWS_ENV, **overrides}


class TestResolveRegion:
    def test_prefers_aws_region_env_var(self):
        env = _aws_env(AWS_REGION="eu-west-1", AWS_DEFAULT_REGION="us-west-2")
        with mock.patch.dict("os.environ", env, clear=True):
            session = boto3.Session()
            assert _resolve_region(session) == "eu-west-1"

    def test_explicit_session_region_beats_aws_region_env_var(self):
        with mock.patch.dict(
            "os.environ", _aws_env(AWS_REGION="eu-west-1"), clear=True
        ):
            session = boto3.Session(region_name="ap-southeast-2")
            assert _resolve_region(session) == "ap-southeast-2"

    def test_falls_back_to_aws_default_region_env_var(self):
        with mock.patch.dict(
            "os.environ", _aws_env(AWS_DEFAULT_REGION="us-west-2"), clear=True
        ):
            session = boto3.Session()
            assert _resolve_region(session) == "us-west-2"

    def test_falls_back_to_config_file_region(self, tmp_path):
        config_file = tmp_path / "aws_config"
        config_file.write_text("[default]\nregion = eu-central-1\n")
        env = _aws_env(AWS_CONFIG_FILE=str(config_file))
        with mock.patch.dict("os.environ", env, clear=True):
            session = boto3.Session()
            assert _resolve_region(session) == "eu-central-1"

    def test_falls_back_to_imds_when_unset(self):
        with mock.patch.dict("os.environ", _aws_env(), clear=True):
            session = boto3.Session()
            with mock.patch("botocore.utils.IMDSRegionProvider") as provider_cls:
                provider_cls.return_value.provide.return_value = "sa-east-1"
                assert _resolve_region(session) == "sa-east-1"

    def test_returns_none_when_nothing_resolves(self):
        with mock.patch.dict("os.environ", _aws_env(), clear=True):
            session = boto3.Session()
            with mock.patch("botocore.utils.IMDSRegionProvider") as provider_cls:
                provider_cls.return_value.provide.side_effect = MetadataRetrievalError(
                    error_msg="no imds"
                )
                assert _resolve_region(session) is None

    def test_returns_none_when_imds_rejects_the_request(self):
        with mock.patch.dict("os.environ", _aws_env(), clear=True):
            session = boto3.Session()
            with mock.patch("botocore.utils.IMDSRegionProvider") as provider_cls:
                provider_cls.return_value.provide.side_effect = BadIMDSRequestError(
                    request=None
                )
                assert _resolve_region(session) is None


class TestGetToken:
    def test_regional_region_name_produces_regional_endpoint(self):
        with mock.patch.dict(
            "os.environ", _aws_env(AWS_REGION="eu-west-1"), clear=True
        ):
            session = boto3.Session(
                aws_access_key_id="test", aws_secret_access_key="test"
            )
            region = _resolve_region(session)
            sts = session.client("sts", region_name=region)
            assert sts.meta.endpoint_url == "https://sts.eu-west-1.amazonaws.com"
            assert sts.meta.region_name != "aws-global"

    @staticmethod
    def _get_token_sts_region(env):
        """Run get_token with a fake STS client and return the region it was given."""
        detector = AWSDetector(context=CredentialContext())
        fake_sts = mock.Mock()
        fake_sts.get_web_identity_token.return_value = {"WebIdentityToken": "jwt"}
        with mock.patch.dict("os.environ", env, clear=True):
            session = boto3.Session(
                aws_access_key_id="test", aws_secret_access_key="test"
            )
            with (
                mock.patch.object(detector, "_session", session),
                mock.patch.object(session, "client", return_value=fake_sts) as client,
            ):
                assert detector.get_token() == "jwt"
        (service_name,), call_kwargs = client.call_args
        assert service_name == "sts"
        return call_kwargs["region_name"]

    def test_passes_resolved_region_to_sts_client(self):
        region = self._get_token_sts_region(_aws_env(AWS_REGION="eu-west-1"))
        assert region == "eu-west-1"

    def test_no_region_resolved_passes_none_region(self):
        with mock.patch("botocore.utils.IMDSRegionProvider") as provider_cls:
            provider_cls.return_value.provide.side_effect = MetadataRetrievalError(
                error_msg="no imds"
            )
            assert self._get_token_sts_region(_aws_env()) is None
