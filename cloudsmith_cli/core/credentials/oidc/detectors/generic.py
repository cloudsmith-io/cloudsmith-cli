"""Generic fallback OIDC detector.

Reads an OIDC token from the ``CLOUDSMITH_OIDC_TOKEN`` environment variable.
Works for Jenkins (with credentials binding plugin), or any custom CI/CD
system that can inject an OIDC token via environment variable.

References:
    https://docs.cloudsmith.com/authentication/setup-jenkins-to-authenticate-to-cloudsmith-using-oidc
    https://plugins.jenkins.io/credentials-binding/
"""

from __future__ import annotations

import os

from .base import EnvironmentDetector


class GenericDetector(EnvironmentDetector):
    """Generic fallback: reads OIDC token from CLOUDSMITH_OIDC_TOKEN env var.

    Works for Jenkins (with credentials binding plugin), or any custom
    CI/CD system that can inject an OIDC token via environment variable.
    """

    name = "Generic (CLOUDSMITH_OIDC_TOKEN)"

    def detect(self) -> bool:
        return bool(os.environ.get("CLOUDSMITH_OIDC_TOKEN"))

    def get_token(self) -> str:
        token = os.environ.get("CLOUDSMITH_OIDC_TOKEN")
        if not token:
            raise ValueError("CLOUDSMITH_OIDC_TOKEN not set")
        return token
