"""OIDC credential provider for CI/CD environments."""

from __future__ import annotations

import logging

from .. import CredentialContext, CredentialProvider, CredentialResult

logger = logging.getLogger(__name__)


class OidcProvider(CredentialProvider):
    """Resolves credentials via OIDC auto-discovery in CI/CD environments.

    Requires CLOUDSMITH_ORG and CLOUDSMITH_SERVICE_SLUG to be set (via env
    vars or click options).  Auto-detects the CI/CD environment, fetches the
    vendor OIDC JWT, and exchanges it for a short-lived Cloudsmith API token.
    """

    name = "oidc"

    def resolve(  # pylint: disable=too-many-return-statements
        self, context: CredentialContext
    ) -> CredentialResult | None:
        if context.oidc_discovery_disabled:
            if context.debug:
                logger.debug(
                    "OidcProvider: OIDC auto-discovery disabled via "
                    "CLOUDSMITH_OIDC_DISCOVERY_DISABLED"
                )
            return None

        org = context.oidc_org
        service_slug = context.oidc_service_slug

        if not org or not service_slug:
            if context.debug:
                logger.debug(
                    "OidcProvider: CLOUDSMITH_ORG and/or CLOUDSMITH_SERVICE_SLUG "
                    "not set, skipping OIDC auto-discovery"
                )
            return None

        from ..oidc.cache import get_cached_token, store_cached_token

        # Check cache BEFORE environment detection — detection can be expensive
        # (e.g. boto3 credential resolution, IMDS calls) and is unnecessary when
        # we already hold a valid exchanged token.
        cached = get_cached_token(context.api_host, org, service_slug)
        if cached:
            logger.debug("OidcProvider: Using cached OIDC token")
            return CredentialResult(
                api_key=cached,
                source_name="oidc",
                source_detail=f"OIDC [cached] (org: {org}, service: {service_slug})",
            )

        from ..oidc.detectors import detect_environment
        from ..oidc.exchange import OidcExchangeError, exchange_oidc_token

        detector = detect_environment(context=context)
        if detector is None:
            if context.debug:
                logger.debug("OidcProvider: No CI/CD environment detected, skipping")
            return None

        try:
            vendor_token = detector.get_token()
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning(
                "OIDC: Failed to retrieve identity token from %s. "
                "Use --debug for details.",
                detector.name,
            )
            logger.debug(
                "OidcProvider: %s token retrieval error",
                detector.name,
                exc_info=True,
            )
            return None

        if not vendor_token:
            logger.warning("OIDC: %s detector returned an empty token.", detector.name)
            return None

        try:
            cloudsmith_token = exchange_oidc_token(
                context=context,
                org=org,
                service_slug=service_slug,
                oidc_token=vendor_token,
            )
        except OidcExchangeError as exc:
            logger.warning("OIDC: Token exchange failed: %s", exc)
            return None
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning(
                "OIDC: Token exchange failed unexpectedly. Use --debug for details."
            )
            logger.debug("OidcProvider: OIDC token exchange error", exc_info=True)
            return None

        if not cloudsmith_token:
            return None

        store_cached_token(context.api_host, org, service_slug, cloudsmith_token)

        return CredentialResult(
            api_key=cloudsmith_token,
            source_name="oidc",
            source_detail=f"OIDC via {detector.name} (org: {org}, service: {service_slug})",
        )
