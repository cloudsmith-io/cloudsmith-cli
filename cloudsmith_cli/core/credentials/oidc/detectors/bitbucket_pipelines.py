"""Bitbucket Pipelines OIDC detector.

Reads OIDC token from the ``BITBUCKET_STEP_OIDC_TOKEN`` environment variable
set when OIDC is enabled for a pipeline step.

References:
    https://support.atlassian.com/bitbucket-cloud/docs/variables-and-secrets/
"""

from __future__ import annotations

import os

from .base import EnvironmentDetector


class BitbucketPipelinesDetector(EnvironmentDetector):
    """Detects Bitbucket Pipelines and reads OIDC token from environment."""

    name = "Bitbucket Pipelines"

    def detect(self) -> bool:
        return bool(os.environ.get("BITBUCKET_STEP_OIDC_TOKEN"))

    def get_token(self) -> str:
        token = os.environ.get("BITBUCKET_STEP_OIDC_TOKEN")
        if not token:
            raise ValueError("BITBUCKET_STEP_OIDC_TOKEN not set")
        return token
