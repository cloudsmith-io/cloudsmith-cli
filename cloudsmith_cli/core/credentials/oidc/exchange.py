"""Cloudsmith OIDC token exchange.

Exchanges a vendor CI/CD OIDC JWT for a short-lived Cloudsmith API token
via the POST /openid/{org}/ endpoint.

References:
    https://help.cloudsmith.io/docs/openid-connect
"""

from __future__ import annotations

import logging
import random
import time

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3


def create_exchange_session(
    proxy: str | None = None,
    ssl_verify: bool = True,
    user_agent: str | None = None,
    headers: dict | None = None,
) -> requests.Session:
    """Create a requests session configured with networking settings.

    Args:
        proxy: HTTP/HTTPS proxy URL.
        ssl_verify: Whether to verify SSL certificates.
        user_agent: Custom user-agent string.
        headers: Additional headers to include.

    Returns:
        Configured requests.Session instance.
    """
    session = requests.Session()

    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    session.verify = ssl_verify

    if user_agent:
        session.headers.update({"User-Agent": user_agent})

    if headers:
        session.headers.update(headers)

    return session


def exchange_oidc_token(
    api_host: str,
    org: str,
    service_slug: str,
    oidc_token: str,
    proxy: str | None = None,
    ssl_verify: bool = True,
    user_agent: str | None = None,
    headers: dict | None = None,
) -> str:
    """Exchange a vendor OIDC JWT for a Cloudsmith API token.

    Args:
        api_host: The Cloudsmith API host (e.g. "https://api.cloudsmith.io").
        org: The Cloudsmith organization slug.
        service_slug: The Cloudsmith service account slug.
        oidc_token: The vendor OIDC JWT to exchange.
        proxy: HTTP/HTTPS proxy URL (optional).
        ssl_verify: Whether to verify SSL certificates (default: True).
        user_agent: Custom user-agent string (optional).
        headers: Additional headers to include (optional).

    Returns:
        The short-lived Cloudsmith API token.

    Raises:
        OidcExchangeError: If the exchange fails after retries.
    """
    # Normalize host
    host = api_host.rstrip("/")
    if not host.startswith("http"):
        host = f"https://{host}"

    url = f"{host}/openid/{org}/"
    payload = {
        "oidc_token": oidc_token,
        "service_slug": service_slug,
    }

    # Create configured session for the exchange
    session = create_exchange_session(
        proxy=proxy,
        ssl_verify=ssl_verify,
        user_agent=user_agent,
        headers=headers,
    )

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.exceptions.RequestException as exc:
            last_error = OidcExchangeError(f"OIDC token exchange request failed: {exc}")
            logger.debug(
                "OIDC exchange attempt %d/%d failed with error: %s",
                attempt,
                MAX_RETRIES,
                exc,
            )
            if attempt < MAX_RETRIES:
                backoff = min(30, (2**attempt) + random.uniform(0, 1))
                logger.debug("Retrying in %.1fs...", backoff)
                time.sleep(backoff)
            continue

        if response.status_code in (200, 201):
            data = response.json()
            token = data.get("token")
            if not token or not isinstance(token, str) or not token.strip():
                raise OidcExchangeError(
                    "Cloudsmith OIDC exchange returned an empty or invalid token"
                )
            return token

        # 4xx errors are not retryable
        if 400 <= response.status_code < 500:
            error_detail = ""
            try:
                error_detail = response.json()
            except Exception:  # pylint: disable=broad-exception-caught
                # Intentionally broad - response could be malformed in various ways
                error_detail = response.text[:1000]  # Truncate long responses

            logger.debug(
                "OIDC exchange 4xx error: %s - %s", response.status_code, error_detail
            )
            raise OidcExchangeError(
                f"OIDC token exchange failed with {response.status_code}: "
                f"{error_detail}"
            )

        # 5xx errors are retryable
        last_error = OidcExchangeError(
            f"OIDC token exchange failed with {response.status_code} "
            f"(attempt {attempt}/{MAX_RETRIES})"
        )
        logger.debug(
            "OIDC exchange attempt %d/%d failed with status %d",
            attempt,
            MAX_RETRIES,
            response.status_code,
        )

        if attempt < MAX_RETRIES:
            backoff = min(30, (2**attempt) + random.uniform(0, 1))
            logger.debug("Retrying in %.1fs...", backoff)
            time.sleep(backoff)

    raise last_error


class OidcExchangeError(Exception):
    """Raised when the OIDC token exchange with Cloudsmith fails."""
