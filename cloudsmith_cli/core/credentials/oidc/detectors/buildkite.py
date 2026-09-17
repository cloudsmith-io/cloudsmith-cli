# Copyright 2026 Cloudsmith Ltd
"""Buildkite OIDC detector.

Requests an OIDC token for the current job through the ``buildkite-agent``
command, which is available in Buildkite pipeline jobs.

References:
    https://buildkite.com/docs/pipelines/security/oidc
    https://buildkite.com/docs/agent/cli/reference/oidc
"""

from __future__ import annotations

import os
import subprocess

from .base import EnvironmentDetector

DEFAULT_AUDIENCE = "cloudsmith"


class BuildkiteDetector(EnvironmentDetector):
    """Detects Buildkite and requests an OIDC token from its agent."""

    name = "Buildkite"
    id = "buildkite"

    def detect(self) -> bool:
        return os.environ.get("BUILDKITE") == "true" and bool(
            os.environ.get("BUILDKITE_JOB_ID")
        )

    def get_token(self) -> str:
        audience = self.context.oidc_audience or DEFAULT_AUDIENCE
        result = subprocess.run(
            [
                "buildkite-agent",
                "oidc",
                "request-token",
                "--audience",
                audience,
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        )
        token = result.stdout.strip()
        if not token:
            raise ValueError("Buildkite agent OIDC request returned an empty token")
        return token
