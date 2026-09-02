"""SSO token refresh against the Cloudsmith API."""

import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

import requests

from . import keyring
from .api.exceptions import ApiException

logger = logging.getLogger(__name__)
REFRESH_REJECTED_STATUSES = frozenset({400, 401, 403, 422})
TOKEN_EXPIRY_LEEWAY = timedelta(seconds=30)


class SsoRenewalStatus(str, Enum):
    """Possible outcomes from renewing an SSO session."""

    RENEWED = "renewed"
    CURRENT = "current"
    MISSING = "missing"
    UNRENEWABLE = "unrenewable"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass
class SsoRenewalResult:
    """Outcome of renewing the SSO tokens stored for one CLI profile."""

    status: SsoRenewalStatus
    access_token: str | None = None
    error: Exception | None = None


@dataclass(frozen=True)
class SsoTokens:
    """Access and refresh tokens stored for an SSO session."""

    access_token: str | None
    refresh_token: str | None


def get_access_token_expiry(access_token):
    """Return the expiry encoded in an SSO access token, if available."""
    if not access_token:
        return None

    try:
        encoded_payload = access_token.split(".", maxsplit=2)[1]
        padding = "=" * (-len(encoded_payload) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded_payload + padding))
        expires_at = payload.get("exp")
        if expires_at is not None:
            return datetime.fromtimestamp(float(expires_at), tz=timezone.utc)
    except (
        IndexError,
        OSError,
        OverflowError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        logger.debug("Failed to decode SSO access token expiry", exc_info=True)

    return None


def access_token_is_valid(access_token, now=None):
    """Return whether an SSO access token is present and not provably expired.

    A token without a readable JWT expiry counts as usable. The API stays
    the authority on whether it still works.
    """
    if not access_token:
        return False

    expires_at = get_access_token_expiry(access_token)
    if expires_at is None:
        return True

    return expires_at + TOKEN_EXPIRY_LEEWAY > (now or datetime.now(tz=timezone.utc))


def _load_sso_tokens(api_host, profile):
    return SsoTokens(
        access_token=keyring.get_access_token(api_host, profile=profile),
        refresh_token=keyring.get_refresh_token(api_host, profile=profile),
    )


def _failed_renewal(api_host, profile, access_token, error):
    keyring.update_refresh_attempted_at(api_host, profile=profile)
    status = (
        SsoRenewalStatus.CURRENT
        if access_token_is_valid(access_token)
        else SsoRenewalStatus.FAILED
    )
    return SsoRenewalResult(status=status, access_token=access_token, error=error)


def _recover_from_rejected_renewal(api_host, profile, previous_tokens, error):
    current_tokens = _load_sso_tokens(api_host, profile)
    if current_tokens != previous_tokens and access_token_is_valid(
        current_tokens.access_token
    ):
        return SsoRenewalResult(
            status=SsoRenewalStatus.CURRENT,
            access_token=current_tokens.access_token,
        )

    deleted = keyring.delete_sso_tokens(api_host, profile=profile, include_legacy=False)
    if not deleted:
        keyring.delete_sso_tokens(api_host)
    return SsoRenewalResult(status=SsoRenewalStatus.REJECTED, error=error)


def _store_renewed_tokens(api_host, profile, access_token, refresh_token):
    from keyring.errors import KeyringError

    try:
        keyring.store_sso_tokens(
            api_host,
            access_token,
            refresh_token,
            profile=profile,
        )
    except KeyringError as exc:
        return SsoRenewalResult(
            status=SsoRenewalStatus.CURRENT,
            access_token=access_token,
            error=exc,
        )
    return SsoRenewalResult(
        status=SsoRenewalStatus.RENEWED,
        access_token=access_token,
    )


def renew_sso_session(api_host, session, profile=None):
    """Renew a keyring SSO session and rotate its refresh token."""
    access_token = keyring.get_access_token(api_host, profile=profile)
    if not access_token:
        return SsoRenewalResult(status=SsoRenewalStatus.MISSING)

    tokens = SsoTokens(
        access_token=access_token,
        refresh_token=keyring.get_refresh_token(api_host, profile=profile),
    )
    if not tokens.refresh_token:
        keyring.update_refresh_attempted_at(api_host, profile=profile)
        return SsoRenewalResult(
            status=SsoRenewalStatus.UNRENEWABLE,
            access_token=tokens.access_token,
        )

    try:
        new_access_token, new_refresh_token = refresh_access_token(
            api_host,
            tokens.access_token,
            tokens.refresh_token,
            session=session,
        )
    except (ApiException, requests.RequestException) as exc:
        if isinstance(exc, ApiException) and exc.status in REFRESH_REJECTED_STATUSES:
            return _recover_from_rejected_renewal(api_host, profile, tokens, error=exc)
        return _failed_renewal(api_host, profile, tokens.access_token, error=exc)

    if not new_access_token:
        error = ValueError("Cloudsmith did not return a new SSO access token.")
        return _failed_renewal(api_host, profile, tokens.access_token, error=error)

    return _store_renewed_tokens(api_host, profile, new_access_token, new_refresh_token)


def raise_for_api_error(response):
    """Raise :class:`ApiException` if *response* failed, keeping the API's detail.

    Without the detail the exception renders as bare status text, so a caller
    reporting it tells the user that something failed but never what.
    """
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        try:
            body = exc.response.json()
        except ValueError:
            body = None

        raise ApiException(
            response.status_code,
            detail=body.get("detail") if isinstance(body, dict) else None,
            headers=exc.response.headers,
            body=exc.response.content,
        )


def refresh_access_token(api_host, access_token, refresh_token, session):
    data = {"refresh_token": refresh_token}
    url = f"{api_host}/user/refresh-token/"

    headers = {"Authorization": f"Bearer {access_token}"}

    response = session.post(
        url,
        data=data,
        headers=headers,
        timeout=30,
    )

    raise_for_api_error(response)

    response_data = response.json()
    access_token = response_data.get("access_token")
    refresh_token = response_data.get("refresh_token")

    return (access_token, refresh_token)
