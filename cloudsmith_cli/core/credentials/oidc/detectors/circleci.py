"""CircleCI OIDC detector.

Reads OIDC token from the ``CIRCLE_OIDC_TOKEN_V2`` or ``CIRCLE_OIDC_TOKEN``
environment variables set by CircleCI's OIDC support.

References:
    https://circleci.com/docs/guides/permissions-authentication/openid-connect-tokens/
    https://docs.cloudsmith.com/integrations/integrating-with-circleci
"""

from __future__ import annotations

import os

from .base import EnvironmentDetector


class CircleCIDetector(EnvironmentDetector):
    """Detects CircleCI and reads OIDC token from environment variable."""

    name = "CircleCI"

    def detect(self) -> bool:
        return os.environ.get("CIRCLECI") == "true" and bool(
            os.environ.get("CIRCLE_OIDC_TOKEN_V2")
            or os.environ.get("CIRCLE_OIDC_TOKEN")
        )

    def get_token(self) -> str:
        token = os.environ.get("CIRCLE_OIDC_TOKEN_V2") or os.environ.get(
            "CIRCLE_OIDC_TOKEN"
        )
        if not token:
            raise ValueError("CircleCI detected but CIRCLE_OIDC_TOKEN not set")
        return token
