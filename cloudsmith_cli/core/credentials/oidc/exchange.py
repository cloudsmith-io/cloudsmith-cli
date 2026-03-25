"""Cloudsmith OIDC token exchange.

Exchanges a vendor OIDC JWT for a short-lived Cloudsmith API token
via the POST /openid/{org}/ endpoint.

References:
    https://help.cloudsmith.io/docs/openid-connect
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import requests

from ..session import create_session

if TYPE_CHECKING:
    from ... import CredentialContext

logger = logging.getLogger(__name__)


def exchange_oidc_token(
    context: CredentialContext,
    org: str,
    service_slug: str,
    oidc_token: str,
) -> str:
    """Exchange a vendor OIDC JWT for a Cloudsmith API token.

    Raises:
        OidcExchangeError: If the exchange fails.
    """
    host = context.api_host.rstrip("/")
    if not host.startswith("http"):
        host = f"https://{host}"

    url = f"{host}/openid/{org}/"
    payload = {
        "oidc_token": oidc_token,
        "service_slug": service_slug,
    }

    session = context.session or create_session()

    try:
        try:
            response = session.post(
                url,
                json=payload,
                timeout=30,
            )
        except requests.exceptions.RequestException as exc:
            raise OidcExchangeError(
                f"OIDC token exchange request failed: {exc}"
            ) from exc

        if response.status_code in (200, 201):
            data = response.json()
            token = data.get("token")
            if not token or not isinstance(token, str) or not token.strip():
                raise OidcExchangeError(
                    "Cloudsmith OIDC exchange returned an empty or invalid token"
                )
            return token

        try:
            error_json = response.json()
            error_detail = error_json.get(
                "detail", error_json.get("error", str(error_json))
            )
        except Exception:  # pylint: disable=broad-exception-caught
            error_detail = response.text[:200]

        raise OidcExchangeError(
            f"OIDC token exchange failed with {response.status_code}: "
            f"{error_detail}"
        )
    finally:
        if not context.session:
            session.close()


class OidcExchangeError(Exception):
    """Raised when the OIDC token exchange with Cloudsmith fails."""
