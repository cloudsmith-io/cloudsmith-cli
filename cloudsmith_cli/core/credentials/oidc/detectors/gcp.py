# Copyright 2026 Cloudsmith Ltd
"""Google Cloud OIDC detector.

Discovers the ambient Google identity via google-auth's Application Default
Credentials chain and mints an OIDC ID token for Cloudsmith.

Requires google-auth (optional dependency): pip install cloudsmith-cli[gcp]

References:
    https://docs.cloud.google.com/iam/docs/authenticate-with-auth-libraries#authenticate-standard
    https://googleapis.dev/python/google-auth/latest/index.html
    https://googleapis.dev/python/google-auth/latest/user-guide.html
    https://github.com/googleapis/google-cloud-python/tree/main/packages/google-auth
"""

from __future__ import annotations

import logging

from .base import EnvironmentDetector

logger = logging.getLogger(__name__)

DEFAULT_AUDIENCE = "cloudsmith"

METADATA_IDENTITY_PATH = "instance/service-accounts/default/identity"


class GCPDetector(EnvironmentDetector):
    """Detects Google Cloud environments and obtains an OIDC ID token."""

    name = "Google Cloud"
    id = "gcp"

    def detect(self) -> bool:
        try:
            import google.auth
            from google.auth import exceptions
        except ImportError:
            logger.debug("google-auth not installed, skipping")
            return False

        try:
            google.auth.default()
            return True
        except exceptions.DefaultCredentialsError:
            return self._on_gce()
        except exceptions.GoogleAuthError:
            logger.debug("Error during Google credential detection", exc_info=True)
            return False

    def get_token(self) -> str:
        audience = self.context.oidc_audience or DEFAULT_AUDIENCE

        try:
            import google.auth
            from google.auth import compute_engine, exceptions
            from google.auth.transport.requests import Request
            from google.oauth2 import credentials as user_creds
        except ImportError as exc:
            raise ValueError(
                "Google Cloud detector requires google-auth; install it with "
                "pip install cloudsmith-cli[gcp]"
            ) from exc

        request = Request()
        try:
            credentials, _ = google.auth.default()
        except exceptions.DefaultCredentialsError:
            token = self._token_from_metadata(audience)
        else:
            if isinstance(credentials, compute_engine.Credentials):
                token = self._token_from_metadata(audience)
            elif isinstance(credentials, user_creds.Credentials):
                token = self._token_from_user_credentials(credentials, request)
            else:
                token = self._token_from_id_token_credentials(audience, request)

        if not token:
            raise ValueError(
                "Google Cloud detector resolved Google credentials but could "
                "not mint an OIDC ID token."
            )
        return token

    def _on_gce(self) -> bool:
        try:
            from google.auth import exceptions
            from google.auth.compute_engine import _metadata
            from google.auth.transport.requests import Request
        except ImportError:
            return False

        try:
            return bool(_metadata.is_on_gce(Request()))
        except exceptions.GoogleAuthError:
            return False

    def _token_from_metadata(self, audience: str) -> str | None:
        try:
            from google.auth import exceptions
            from google.auth.compute_engine import _metadata
            from google.auth.transport.requests import Request
        except ImportError:
            return None

        try:
            token = _metadata.get(
                Request(),
                METADATA_IDENTITY_PATH,
                params={"audience": audience, "format": "full"},
            )
        except exceptions.GoogleAuthError:
            logger.debug("Metadata ID token fetch failed", exc_info=True)
            return None
        if not isinstance(token, str):
            return None
        return token.strip() or None

    def _token_from_user_credentials(self, credentials, request) -> str | None:
        try:
            from google.auth import exceptions
        except ImportError:
            return None

        try:
            credentials.refresh(request)
        except exceptions.GoogleAuthError:
            logger.debug("ADC id_token refresh failed", exc_info=True)
            return None
        return getattr(credentials, "id_token", None) or None

    def _token_from_id_token_credentials(self, audience: str, request) -> str | None:
        try:
            from google.auth import exceptions
            from google.oauth2 import id_token
        except ImportError:
            return None

        try:
            id_credentials = id_token.fetch_id_token_credentials(audience, request)
            id_credentials.refresh(request)
            return id_credentials.token or None
        except exceptions.GoogleAuthError:
            logger.debug("ID token credentials fetch failed", exc_info=True)
            return None
