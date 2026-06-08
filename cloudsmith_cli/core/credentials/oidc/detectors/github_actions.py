# Copyright 2026 Cloudsmith Ltd
"""GitHub Actions OIDC detector.

Fetches an OIDC token via the Actions runtime HTTP endpoint, using the
``ACTIONS_ID_TOKEN_REQUEST_URL`` and ``ACTIONS_ID_TOKEN_REQUEST_TOKEN``
variables exposed when a workflow requests ``id-token: write`` permission.

References:
    https://docs.github.com/en/actions/reference/security/oidc
    https://docs.cloudsmith.com/authentication/setup-cloudsmith-to-authenticate-with-oidc-in-github-actions
"""

from __future__ import annotations

import os
from urllib.parse import quote

from ....rest import create_requests_session as create_session
from .base import EnvironmentDetector

DEFAULT_AUDIENCE = "cloudsmith"


class GitHubActionsDetector(EnvironmentDetector):
    """Detects GitHub Actions and fetches an OIDC token via HTTP request."""

    name = "GitHub Actions"

    def detect(self) -> bool:
        return (
            os.environ.get("GITHUB_ACTIONS") == "true"
            and bool(os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"))
            and bool(os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN"))
        )

    def get_token(self) -> str:
        request_url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
        request_token = os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]

        audience = self.context.oidc_audience or DEFAULT_AUDIENCE
        separator = "&" if "?" in request_url else "?"
        url = f"{request_url}{separator}audience={quote(audience, safe='')}"

        session = self.context.session or create_session()
        try:
            response = session.get(
                url,
                headers={
                    "Authorization": f"Bearer {request_token}",
                    "Accept": "application/json; api-version=2.0",
                },
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            token = data.get("value")
            if not token:
                raise ValueError("GitHub Actions OIDC response did not contain a token")
            return token
        finally:
            if not self.context.session:
                session.close()
