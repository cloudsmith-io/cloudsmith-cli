"""Keyring credential provider."""

from __future__ import annotations

import logging

from ....core import keyring
from ...api.exceptions import ApiException
from ...sso import refresh_access_token
from ..models import CredentialContext, CredentialResult
from ..provider import CredentialProvider

logger = logging.getLogger(__name__)

REFRESH_REJECTED_STATUSES = (400, 401, 403, 422)


def _handle_refresh_failure(context, wipe_tokens):
    """Record a refresh failure and clear rejected tokens.

    A definitive rejection means the stored tokens are dead. Remove the
    profile's own entries so the CLI returns to a clean logged-out
    state instead of retrying dead tokens on every command. When the
    profile has no entries of its own, the rejected tokens came from
    the legacy unscoped entries, so remove those. When no entry was
    removed, stamp the attempt time to throttle the next refresh.
    """
    tokens_removed = False
    if wipe_tokens:
        tokens_removed = keyring.delete_sso_tokens(
            context.api_host, profile=context.profile, include_legacy=False
        )
        if not tokens_removed:
            tokens_removed = keyring.delete_sso_tokens(context.api_host)
    if not tokens_removed:
        keyring.update_refresh_attempted_at(context.api_host, profile=context.profile)
    context.keyring_refresh_failed = True


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
            if keyring.should_refresh_access_token(api_host, profile=profile):
                if not context.session:
                    logger.debug(
                        "Session unavailable; skipping token refresh, using existing token"
                    )
                else:
                    refresh_token = keyring.get_refresh_token(api_host, profile=profile)
                    if not refresh_token:
                        logger.debug(
                            "No refresh token stored; using the existing access token"
                        )
                    else:
                        new_access_token, new_refresh_token = refresh_access_token(
                            api_host,
                            access_token,
                            refresh_token,
                            session=context.session,
                        )
                        if not new_access_token:
                            logger.debug("The refresh response has no access token")
                            _handle_refresh_failure(context, wipe_tokens=False)
                            return None
                        keyring.store_sso_tokens(
                            api_host,
                            new_access_token,
                            new_refresh_token,
                            profile=profile,
                        )
                        access_token = new_access_token
        except Exception as exc:  # pylint: disable=broad-exception-caught
            wipe_tokens = (
                isinstance(exc, ApiException)
                and exc.status in REFRESH_REJECTED_STATUSES
            )
            if wipe_tokens:
                logger.debug(
                    "SSO refresh rejected; clearing stored SSO tokens", exc_info=True
                )
            else:
                logger.debug("Failed to refresh SAML token", exc_info=True)
            _handle_refresh_failure(context, wipe_tokens=wipe_tokens)
            return None

        return CredentialResult(
            api_key=access_token,
            source_name="keyring",
            source_detail="SAML token from system keyring",
            auth_type="bearer",
        )
