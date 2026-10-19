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
from typing import TYPE_CHECKING

from .base import EnvironmentDetector

if TYPE_CHECKING:
    from google.auth.credentials import Credentials
    from google.auth.transport.requests import Request

    from ...models import CredentialContext

logger = logging.getLogger(__name__)

DEFAULT_AUDIENCE = "cloudsmith"

METADATA_IDENTITY_PATH = "instance/service-accounts/default/identity"


class GCPDetector(EnvironmentDetector):
    """Detects Google Cloud environments and obtains an OIDC ID token."""

    name = "Google Cloud"
    id = "gcp"

    def __init__(self, context: CredentialContext):
        super().__init__(context)
        self._credentials: Credentials | None = None

    def detect(self) -> bool:
        try:
            import google.auth
            from google.auth import compute_engine, exceptions, impersonated_credentials
            from google.oauth2 import credentials as user_creds
            from google.oauth2 import service_account
        except ImportError:
            logger.debug("google-auth not installed, skipping")
            return False

        try:
            credentials, _ = google.auth.default()
        except exceptions.GoogleAuthError:
            logger.debug("Error during Google credential detection", exc_info=True)
            return False

        if isinstance(credentials, user_creds.Credentials):
            audience = self.context.oidc_audience or DEFAULT_AUDIENCE
            if audience != credentials.client_id:
                logger.debug(
                    "Google user ADC audience does not match %s, skipping", audience
                )
                return False

        if not isinstance(
            credentials,
            (
                compute_engine.Credentials,
                impersonated_credentials.Credentials,
                service_account.Credentials,
                user_creds.Credentials,
            ),
        ):
            logger.debug(
                "Google ADC type %s does not support ID token generation, skipping",
                type(credentials).__name__,
            )
            return False
        self._credentials = credentials
        return True

    def get_token(self) -> str:
        audience = self.context.oidc_audience or DEFAULT_AUDIENCE

        try:
            import google.auth
            from google.auth import compute_engine, impersonated_credentials
            from google.auth.transport.requests import Request
            from google.oauth2 import credentials as user_creds
            from google.oauth2 import service_account
        except ImportError as exc:
            raise ValueError(
                "Google Cloud detector requires google-auth; install it with "
                "pip install cloudsmith-cli[gcp]"
            ) from exc

        request = Request()
        credentials = self._credentials
        if credentials is None:
            credentials, _ = google.auth.default()

        if isinstance(credentials, compute_engine.Credentials):
            token = self._token_from_metadata(credentials, audience, request)
        elif isinstance(credentials, user_creds.Credentials):
            token = self._token_from_user_credentials(credentials, audience, request)
        else:
            if isinstance(credentials, impersonated_credentials.Credentials):
                id_credentials = impersonated_credentials.IDTokenCredentials(
                    credentials, target_audience=audience, include_email=True
                )
            elif isinstance(credentials, service_account.Credentials):
                id_credentials = service_account.IDTokenCredentials(
                    credentials.signer,
                    credentials.service_account_email,
                    # google-auth has no public token URI accessor or conversion
                    # from an already-resolved service-account credential.
                    token_uri=credentials._token_uri,
                    target_audience=audience,
                )
            else:
                raise TypeError(
                    "Google ADC credentials cannot mint an OIDC ID token. "
                    "Use an attached service account, a service-account key, or "
                    "gcloud auth application-default login "
                    "--impersonate-service-account=SERVICE_ACCOUNT_EMAIL."
                )
            id_credentials.refresh(request)
            token = id_credentials.token

        if not isinstance(token, str) or not token.strip():
            raise ValueError(
                "Google Cloud detector resolved Google credentials but could "
                "not mint an OIDC ID token."
            )
        return token.strip()

    def _token_from_metadata(
        self, credentials: Credentials, audience: str, request: Request
    ) -> str | None:
        from google.auth import exceptions, impersonated_credentials
        from google.auth.compute_engine import _metadata

        try:
            return _metadata.get(
                request,
                METADATA_IDENTITY_PATH,
                params={"audience": audience, "format": "full"},
            )
        except exceptions.TransportError as exc:
            # Some Cloud Build metadata servers expose access tokens but no
            # identity endpoint. Only a missing endpoint should use IAM instead.
            response = exc.args[1] if len(exc.args) > 1 else None
            if getattr(response, "status", None) != 404:
                raise

        logger.debug(
            "Metadata identity endpoint unavailable; using IAM generateIdToken"
        )
        email = _metadata.get(request, "instance/service-accounts/default/email")
        if not isinstance(email, str) or not email.strip():
            raise ValueError("Google metadata returned no service-account email.")
        target = impersonated_credentials.Credentials(
            source_credentials=credentials,
            target_principal=email.strip(),
            target_scopes=[],
        )
        id_credentials = impersonated_credentials.IDTokenCredentials(
            target, target_audience=audience, include_email=True
        )
        id_credentials.refresh(request)
        return id_credentials.token

    def _token_from_user_credentials(
        self, credentials, audience: str, request: Request
    ) -> str | None:
        from google.auth import jwt

        credentials.refresh(request)
        token = credentials.id_token
        if token and jwt.decode(token, verify=False).get("aud") != audience:
            raise ValueError(
                "Google user ADC ID tokens use the OAuth client ID as their audience, "
                "not the requested OIDC audience. Set --oidc-audience to that client "
                "ID and configure Cloudsmith to trust it, or use "
                "gcloud auth application-default login "
                "--impersonate-service-account=SERVICE_ACCOUNT_EMAIL."
            )
        return token
