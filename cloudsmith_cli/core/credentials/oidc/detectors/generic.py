# Copyright 2026 Cloudsmith Ltd
"""Generic fallback OIDC detector.

Reads an OIDC token from the ``CLOUDSMITH_OIDC_TOKEN`` environment variable.
Works for Jenkins (with the credentials binding plugin), or any custom CI/CD
system that can inject an OIDC token via an environment variable.

References:
    https://docs.cloudsmith.com/authentication/setup-jenkins-to-authenticate-to-cloudsmith-using-oidc
    https://plugins.jenkins.io/credentials-binding/
"""

from __future__ import annotations

import os

from .base import EnvironmentDetector

TOKEN_ENV_VAR = "CLOUDSMITH_OIDC_TOKEN"


class GenericDetector(EnvironmentDetector):
    """Generic fallback: reads the OIDC token from CLOUDSMITH_OIDC_TOKEN.

    Works for Jenkins (with the credentials binding plugin), or any custom
    CI/CD system that can inject an OIDC token via an environment variable.
    """

    name = "Generic"

    def detect(self) -> bool:
        return bool((os.environ.get(TOKEN_ENV_VAR) or "").strip())

    def get_token(self) -> str:
        token = (os.environ.get(TOKEN_ENV_VAR) or "").strip()
        if not token:
            raise ValueError(
                f"Generic OIDC detector selected but {TOKEN_ENV_VAR} is not "
                "set. Set it to the OIDC JWT to exchange for a Cloudsmith token."
            )
        return token
