# Copyright 2026 Cloudsmith Ltd
"""Bitbucket Pipelines OIDC detector.

Reads an OIDC token from the ``BITBUCKET_STEP_OIDC_TOKEN`` environment variable,
which Bitbucket populates when ``oidc: true`` is set on a pipeline step.

References:
    https://support.atlassian.com/bitbucket-cloud/docs/integrate-pipelines-with-resource-servers-using-oidc/
    https://support.atlassian.com/bitbucket-cloud/docs/variables-and-secrets/
"""

from __future__ import annotations

import os

from .base import EnvironmentDetector


class BitbucketPipelinesDetector(EnvironmentDetector):
    """Detects Bitbucket Pipelines and reads its OIDC token from environment."""

    name = "Bitbucket Pipelines"

    def detect(self) -> bool:
        return bool(os.environ.get("BITBUCKET_STEP_OIDC_TOKEN"))

    def get_token(self) -> str:
        token = os.environ.get("BITBUCKET_STEP_OIDC_TOKEN")
        if not token:
            raise ValueError(
                "BITBUCKET_STEP_OIDC_TOKEN is not set. Enable OIDC on the "
                "pipeline step with 'oidc: true'."
            )
        return token
