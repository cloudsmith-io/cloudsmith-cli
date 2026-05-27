"""AWS OIDC detector.

Uses boto3 to auto-discover AWS credentials and calls STS GetWebIdentityToken
to obtain a signed JWT for Cloudsmith.

Requires boto3 (optional dependency): pip install cloudsmith-cli[aws]

References:
    https://cloudsmith.com/blog/authenticate-to-cloudsmith-with-your-aws-identity
"""

from __future__ import annotations

import logging

from .base import EnvironmentDetector

logger = logging.getLogger(__name__)

DEFAULT_AUDIENCE = "cloudsmith"


class AWSDetector(EnvironmentDetector):
    """Detects AWS environments and obtains a JWT via STS GetWebIdentityToken."""

    name = "AWS"

    def __init__(self, context):
        super().__init__(context)
        self._session = None

    def detect(self) -> bool:
        try:
            import boto3
            from botocore.exceptions import (
                BotoCoreError,
                ClientError,
                MissingDependencyException,
                NoCredentialsError,
            )
        except ImportError:
            logger.debug("AWSDetector: boto3 not installed, skipping")
            return False

        try:
            self._session = boto3.Session()
            credentials = self._session.get_credentials()
            if credentials is None:
                return False
            # Resolve to verify credentials are usable
            credentials = credentials.get_frozen_credentials()
            return bool(credentials.access_key)
        except MissingDependencyException as e:
            logger.debug(
                "AWSDetector: Missing boto3 dependency for SSO credentials: %s. "
                "Install with: pip install 'botocore[crt]' or 'boto3[crt]'",
                e,
            )
            return False
        except (BotoCoreError, NoCredentialsError, ClientError):
            return False
        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug(
                "AWSDetector: unexpected error during detection", exc_info=True
            )
            return False

    def get_token(self) -> str:
        import boto3  # pylint: disable=import-error

        audience = self.context.oidc_audience or DEFAULT_AUDIENCE
        session = self._session or boto3.Session()
        sts = session.client("sts")
        response = sts.get_web_identity_token(
            Audience=[audience],
            SigningAlgorithm="RS256",
        )

        token = response.get("WebIdentityToken")
        if not token:
            raise ValueError(
                "AWS STS GetWebIdentityToken did not return a WebIdentityToken"
            )
        return token
