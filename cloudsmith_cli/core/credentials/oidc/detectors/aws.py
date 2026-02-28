"""AWS OIDC detector.

Uses boto3 to auto-discover AWS credentials (via any mechanism: env vars,
config files, IAM instance profiles, IRSA, etc.) and then calls
STS GetWebIdentityToken to obtain a signed JWT for Cloudsmith.

**Note:** Requires boto3 (optional dependency).
Install with: pip install cloudsmith-cli[aws]

**For AWS SSO users:** Requires the CRT extension, which is automatically included
in the [aws] extra. If you install boto3 separately, use: pip install boto3[crt]

References:
    https://cloudsmith.com/blog/authenticate-to-cloudsmith-with-your-aws-identity
    https://aws.amazon.com/blogs/aws/simplify-access-to-external-services-using-aws-iam-outbound-identity-federation/
"""

from __future__ import annotations

import logging

from .base import EnvironmentDetector, get_oidc_audience

logger = logging.getLogger(__name__)


class AWSDetector(EnvironmentDetector):
    """Detects AWS environments and obtains a JWT via STS GetWebIdentityToken.

    Requires boto3 (optional dependency): pip install cloudsmith-cli[aws]
    """

    name = "AWS"

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
            session = boto3.Session()
            credentials = session.get_credentials()
            if credentials is None:
                return False
            # Resolve to verify they are actually usable
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
            # Catch-all for unexpected boto3 errors
            logger.debug(
                "AWSDetector: unexpected error during detection", exc_info=True
            )
            return False

    def get_token(self) -> str:
        import boto3  # pylint: disable=import-error

        audience = get_oidc_audience()
        sts = boto3.client("sts")
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
