"""GitHub Actions OIDC detector.

Fetches OIDC token via the Actions runtime HTTP endpoint.

References:
    https://docs.github.com/en/actions/reference/security/oidc
    https://docs.cloudsmith.com/authentication/setup-cloudsmith-to-authenticate-with-oidc-in-github-actions
"""

from __future__ import annotations

import os

import requests

from .base import EnvironmentDetector, get_oidc_audience


class GitHubActionsDetector(EnvironmentDetector):
    """Detects GitHub Actions and fetches OIDC token via HTTP request."""

    name = "GitHub Actions"

    def detect(self) -> bool:
        return (
            os.environ.get("GITHUB_ACTIONS") == "true"
            and bool(os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"))
            and bool(os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN"))
        )

    def get_token(self) -> str:
        from urllib.parse import quote

        request_url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
        request_token = os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]

        audience = get_oidc_audience()
        separator = "&" if "?" in request_url else "?"
        url = f"{request_url}{separator}audience={quote(audience, safe='')}"

        response = requests.get(
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
