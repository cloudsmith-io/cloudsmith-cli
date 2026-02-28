"""Credential providers for the Cloudsmith CLI."""

from __future__ import annotations

import logging
import os

from . import CredentialContext, CredentialProvider, CredentialResult

logger = logging.getLogger(__name__)


class EnvironmentVariableProvider(CredentialProvider):
    """Resolves credentials from the CLOUDSMITH_API_KEY environment variable."""

    name = "environment_variable"

    def resolve(self, context: CredentialContext) -> CredentialResult | None:
        api_key = os.environ.get("CLOUDSMITH_API_KEY")
        if api_key and api_key.strip():
            suffix = api_key.strip()[-4:]
            return CredentialResult(
                api_key=api_key.strip(),
                source_name="environment_variable",
                source_detail=f"CLOUDSMITH_API_KEY env var (ends with ...{suffix})",
            )
        return None


class ConfigFileProvider(CredentialProvider):
    """Resolves credentials from the credentials.ini config file."""

    name = "config_file"

    def resolve(self, context: CredentialContext) -> CredentialResult | None:
        from ...cli.config import CredentialsReader

        reader = CredentialsReader
        path = context.creds_file_path

        try:
            config = {}
            if path and os.path.exists(path):
                if os.path.isdir(path):
                    reader.config_searchpath.insert(0, path)
                else:
                    reader.config_files.insert(0, path)

            raw_config = reader.read_config()
            values = raw_config.get("default", {})
            config.update(values)

            if context.profile and context.profile != "default":
                profile_values = raw_config.get(f"profile:{context.profile}", {})
                config.update(profile_values)

            api_key = config.get("api_key")
            if api_key and isinstance(api_key, str):
                api_key = api_key.strip().strip("'\"")
                if api_key:
                    source_files = reader.find_existing_files()
                    source = source_files[0] if source_files else "credentials.ini"
                    return CredentialResult(
                        api_key=api_key,
                        source_name="config_file",
                        source_detail=f"credentials.ini ({source})",
                    )
        except Exception:  # pylint: disable=broad-exception-caught
            # Config file errors can be varied (permissions, parse errors, etc.)
            logger.debug("ConfigFileProvider failed to read config", exc_info=True)

        return None


class KeyringProvider(CredentialProvider):
    """Resolves credentials from SSO tokens stored in the system keyring."""

    name = "keyring"

    def resolve(self, context: CredentialContext) -> CredentialResult | None:
        from ...cli import saml
        from ...core import keyring
        from ...core.api.exceptions import ApiException

        if not keyring.should_use_keyring():
            return None

        api_host = context.api_host
        access_token = keyring.get_access_token(api_host)

        if not access_token:
            return None

        # Attempt refresh if needed
        try:
            if keyring.should_refresh_access_token(api_host):
                refresh_token = keyring.get_refresh_token(api_host)
                import requests

                session = requests.Session()
                new_access_token, new_refresh_token = saml.refresh_access_token(
                    api_host,
                    access_token,
                    refresh_token,
                    session=session,
                )
                keyring.store_sso_tokens(api_host, new_access_token, new_refresh_token)
                access_token = new_access_token
        except (ApiException, Exception):  # pylint: disable=broad-exception-caught
            # SSO refresh can fail in various ways (network, API errors, keyring issues)
            keyring.update_refresh_attempted_at(api_host)
            logger.debug("Failed to refresh SSO token", exc_info=True)

        return CredentialResult(
            api_key=access_token,
            source_name="keyring",
            source_detail="SSO token from system keyring",
        )

    @staticmethod
    def is_bearer_token() -> bool:
        """Keyring tokens are Bearer tokens, not API keys."""
        return True


class OidcProvider(CredentialProvider):
    """Resolves credentials via OIDC auto-discovery in CI/CD environments.

    Requires CLOUDSMITH_ORG and CLOUDSMITH_SERVICE_SLUG environment variables.
    Auto-detects the CI/CD environment, fetches the vendor OIDC JWT, and
    exchanges it for a short-lived Cloudsmith API token.
    """

    name = "oidc"

    def resolve(  # pylint: disable=too-many-return-statements
        self, context: CredentialContext
    ) -> CredentialResult | None:
        import re

        org = os.environ.get("CLOUDSMITH_ORG", "").strip()
        service_slug = os.environ.get("CLOUDSMITH_SERVICE_SLUG", "").strip()

        if not org or not service_slug:
            if context.debug:
                logger.debug(
                    "OidcProvider: CLOUDSMITH_ORG and/or CLOUDSMITH_SERVICE_SLUG "
                    "not set, skipping OIDC auto-discovery"
                )
            return None

        # Validate slug format (alphanumeric, hyphens, underscores)
        if not re.match(r"^[a-zA-Z0-9_-]+$", org):
            logger.warning("OidcProvider: Invalid CLOUDSMITH_ORG format: %s", org)
            return None
        if not re.match(r"^[a-zA-Z0-9_-]+$", service_slug):
            logger.warning(
                "OidcProvider: Invalid CLOUDSMITH_SERVICE_SLUG format: %s", service_slug
            )
            return None

        from .oidc.detectors import detect_environment
        from .oidc.exchange import exchange_oidc_token

        # Detect CI/CD environment and get vendor JWT
        detector = detect_environment(
            debug=context.debug,
            proxy=context.proxy,
            ssl_verify=context.ssl_verify,
            user_agent=context.user_agent,
            headers=context.headers,
        )
        if detector is None:
            if context.debug:
                logger.debug("OidcProvider: No CI/CD environment detected, skipping")
            return None

        try:
            vendor_token = detector.get_token()
        except Exception:  # pylint: disable=broad-exception-caught
            # Detector token retrieval can fail in various ways
            logger.debug(
                "OidcProvider: Failed to retrieve OIDC token from %s",
                detector.name,
                exc_info=True,
            )
            return None

        if not vendor_token:
            logger.debug(
                "OidcProvider: %s detector returned empty token", detector.name
            )
            return None

        # Check cache before doing a full exchange
        from .oidc.cache import get_cached_token, store_cached_token

        cached = get_cached_token(context.api_host, org, service_slug)
        if cached:
            logger.debug("OidcProvider: Using cached OIDC token")
            return CredentialResult(
                api_key=cached,
                source_name="oidc",
                source_detail=f"OIDC via {detector.name} [cached] (org: {org}, service: {service_slug})",
            )

        # Exchange vendor JWT for Cloudsmith token
        try:
            cloudsmith_token = exchange_oidc_token(
                api_host=context.api_host,
                org=org,
                service_slug=service_slug,
                oidc_token=vendor_token,
                proxy=context.proxy,
                ssl_verify=context.ssl_verify,
                user_agent=context.user_agent,
                headers=context.headers,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            # Exchange can fail for various reasons (network, API errors, auth issues)
            logger.debug("OidcProvider: OIDC token exchange failed", exc_info=True)
            return None

        if not cloudsmith_token:
            return None

        # Cache the token for future use
        store_cached_token(context.api_host, org, service_slug, cloudsmith_token)

        return CredentialResult(
            api_key=cloudsmith_token,
            source_name="oidc",
            source_detail=f"OIDC via {detector.name} (org: {org}, service: {service_slug})",
        )
