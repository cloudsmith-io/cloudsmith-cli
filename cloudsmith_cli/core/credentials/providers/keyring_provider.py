"""Keyring credential provider."""

from __future__ import annotations

import logging

from .. import CredentialContext, CredentialProvider, CredentialResult

logger = logging.getLogger(__name__)


class KeyringProvider(CredentialProvider):
    """Resolves credentials from SAML tokens stored in the system keyring."""

    name = "keyring"

    def resolve(self, context: CredentialContext) -> CredentialResult | None:
        from ....cli.saml import refresh_access_token
        from ....core import keyring

        if not keyring.should_use_keyring():
            return None

        api_host = context.api_host
        access_token = keyring.get_access_token(api_host)

        if not access_token:
            return None

        try:
            if keyring.should_refresh_access_token(api_host):
                if not context.session:
                    return None
                refresh_token = keyring.get_refresh_token(api_host)
                new_access_token, new_refresh_token = refresh_access_token(
                    api_host,
                    access_token,
                    refresh_token,
                    session=context.session,
                )
                keyring.store_sso_tokens(api_host, new_access_token, new_refresh_token)
                access_token = new_access_token
        except Exception:  # pylint: disable=broad-exception-caught
            keyring.update_refresh_attempted_at(api_host)
            context.keyring_refresh_failed = True
            logger.debug("Failed to refresh SAML token", exc_info=True)
            return None

        return CredentialResult(
            api_key=access_token,
            source_name="keyring",
            source_detail="SAML token from system keyring",
            auth_type="bearer",
        )
