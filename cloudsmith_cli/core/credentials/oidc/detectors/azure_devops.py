# Copyright 2026 Cloudsmith Ltd
"""Azure DevOps OIDC detector.

Fetches an OIDC token via the ``SYSTEM_OIDCREQUESTURI`` HTTP endpoint using
the pipeline's ``SYSTEM_ACCESSTOKEN`` for authorization.

The audience is not caller-configurable: Azure DevOps always mints the token
with a fixed audience (``api://AzureADTokenExchange``) and ignores any audience
supplied in the request, so the request is an empty POST (matching the Azure
SDK's AzurePipelinesCredential).

References:
    https://learn.microsoft.com/en-us/azure/devops/release-notes/2024/sprint-240-update#pipelines-and-tasks-populate-variables-to-customize-workload-identity-federation-authentication
    https://github.com/Azure/azure-sdk-for-go/blob/main/sdk/azidentity/azure_pipelines_credential.go
    https://docs.cloudsmith.com/integrations/integrating-with-azure-devops
    https://cloudsmith.com/changelog/native-oidc-authentication-for-azure-devops
"""

from __future__ import annotations

import os

from ....rest import create_requests_session as create_session
from .base import EnvironmentDetector

API_VERSION = "7.1"


class AzureDevOpsDetector(EnvironmentDetector):
    """Detects Azure DevOps and fetches an OIDC token via HTTP POST."""

    name = "Azure DevOps"
    id = "azure_devops"

    def detect(self) -> bool:
        return bool(os.environ.get("SYSTEM_OIDCREQUESTURI")) and bool(
            os.environ.get("SYSTEM_ACCESSTOKEN")
        )

    def get_token(self) -> str:
        request_uri = os.environ["SYSTEM_OIDCREQUESTURI"]
        access_token = os.environ["SYSTEM_ACCESSTOKEN"]

        # The Azure DevOps OIDC endpoint rejects requests without an explicit
        # api-version (HTTP 400), so it must always be supplied.
        separator = "&" if "?" in request_uri else "?"
        url = f"{request_uri}{separator}api-version={API_VERSION}"

        session = self.context.session or create_session()
        try:
            response = session.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-TFS-FedAuthRedirect": "Suppress",
                },
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            token = data.get("oidcToken")
            if not token:
                raise ValueError(
                    "Azure DevOps OIDC response did not contain an oidcToken"
                )
            return token
        finally:
            if not self.context.session:
                session.close()
