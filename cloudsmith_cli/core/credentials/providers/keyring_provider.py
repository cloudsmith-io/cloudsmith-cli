"""Keyring credential provider."""

from __future__ import annotations

import logging

from ....core import keyring
from ...sso import SsoRenewalStatus, access_token_is_valid, renew_sso_session
from ..models import CredentialContext, CredentialResult
from ..provider import CredentialProvider

logger = logging.getLogger(__name__)


def _credential(access_token):
    return CredentialResult(
        api_key=access_token,
        source_name="keyring",
        source_detail="SAML token from system keyring",
        auth_type="bearer",
    )


def _access_token_from_renewal(context, renewal, held_access_token):
    if renewal.status == SsoRenewalStatus.REJECTED:
        context.keyring_refresh_failed = True
        context.keyring_refresh_rejected = True
        return None
    if renewal.status == SsoRenewalStatus.MISSING:
        context.keyring_refresh_failed = True
        return held_access_token if access_token_is_valid(held_access_token) else None
    if renewal.status == SsoRenewalStatus.FAILED:
        context.keyring_refresh_failed = True
        return None
    if renewal.status == SsoRenewalStatus.UNRENEWABLE:
        context.keyring_refresh_failed = True
        context.keyring_refresh_unrenewable = True
        if not access_token_is_valid(renewal.access_token):
            return None
    if renewal.status == SsoRenewalStatus.CURRENT and renewal.error:
        context.keyring_refresh_failed = True
    return renewal.access_token


def _recover_from_unexpected_refresh_error(context, access_token):
    context.keyring_refresh_failed = True
    keyring.update_refresh_attempted_at(context.api_host, profile=context.profile)
    return access_token if access_token_is_valid(access_token) else None


def _refresh_access_token(context, access_token):
    if context.skip_keyring_refresh or not keyring.should_refresh_access_token(
        context.api_host,
        access_token=access_token,
        profile=context.profile,
    ):
        return access_token

    if not context.session:
        logger.debug(
            "Session unavailable; skipping token refresh, using existing token"
        )
        return access_token

    renewal = renew_sso_session(
        context.api_host,
        context.session,
        profile=context.profile,
    )
    return _access_token_from_renewal(context, renewal, access_token)


class KeyringProvider(CredentialProvider):
    """Resolves credentials from SAML tokens stored in the system keyring."""

    name = "keyring"

    def resolve(self, context: CredentialContext) -> CredentialResult | None:
        if not keyring.should_use_keyring():
            return None

        api_host = context.api_host
        profile = context.profile
        access_token = keyring.get_access_token(api_host, profile=profile)

        if not access_token:
            return None

        try:
            access_token = _refresh_access_token(context, access_token)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug("Failed to refresh SAML token", exc_info=True)
            access_token = _recover_from_unexpected_refresh_error(context, access_token)

        return _credential(access_token) if access_token else None
