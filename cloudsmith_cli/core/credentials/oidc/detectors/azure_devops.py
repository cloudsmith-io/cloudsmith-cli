"""Azure DevOps OIDC detector.

Fetches OIDC token via the ``SYSTEM_OIDCREQUESTURI`` HTTP endpoint using
the pipeline's ``SYSTEM_ACCESSTOKEN`` for authorization.

References:
    https://learn.microsoft.com/en-us/azure/devops/release-notes/2024/sprint-240-update#pipelines-and-tasks-populate-variables-to-customize-workload-identity-federation-authentication
    https://docs.cloudsmith.com/integrations/integrating-with-azure-devops
    https://cloudsmith.com/changelog/native-oidc-authentication-for-azure-devops
"""

from __future__ import annotations

import os

import requests

from .base import EnvironmentDetector, get_oidc_audience


class AzureDevOpsDetector(EnvironmentDetector):
    """Detects Azure DevOps and fetches OIDC token via HTTP POST."""

    name = "Azure DevOps"

    def detect(self) -> bool:
        return bool(os.environ.get("SYSTEM_OIDCREQUESTURI")) and bool(
            os.environ.get("SYSTEM_ACCESSTOKEN")
        )

    def get_token(self) -> str:
        request_uri = os.environ["SYSTEM_OIDCREQUESTURI"]
        access_token = os.environ["SYSTEM_ACCESSTOKEN"]
        audience = get_oidc_audience()

        response = requests.post(
            request_uri,
            json={"audience": audience},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        token = data.get("oidcToken")
        if not token:
            raise ValueError("Azure DevOps OIDC response did not contain an oidcToken")
        return token
