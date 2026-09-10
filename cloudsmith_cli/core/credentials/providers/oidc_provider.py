"""OIDC credential provider."""

from __future__ import annotations

import json
import logging

from ..models import CredentialContext, CredentialResult
from ..provider import CredentialProvider

logger = logging.getLogger(__name__)


def _warn(context: CredentialContext, message: str, *args: object) -> None:
    """Write a user-facing warning to CLI stderr, falling back to logging."""
    rendered = message % args if args else message
    if context.warning_writer:
        context.warning_writer(rendered)
    else:
        logger.warning("%s", rendered)


def _log_exchange_diagnostics(
    *,
    context: CredentialContext,
    detector_name: str,
    org: str,
    service_slug: str,
    vendor_token: str,
) -> None:
    """Log the inputs needed to diagnose a failed exchange without the raw JWT."""
    _warn(context, "OIDC exchange diagnostics:")
    _warn(context, "  Workspace: %s", org)
    _warn(context, "  Service slug: %s", service_slug)
    _warn(context, "  Cloudsmith API host: %s", context.api_host)
    _warn(context, "  Vendor detector: %s", detector_name)

    try:
        import jwt

        header = jwt.get_unverified_header(vendor_token)
        claims = jwt.decode(
            vendor_token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
                "verify_iss": False,
            },
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        _warn(context, "  Vendor JWT could not be decoded: %s", exc)
        return

    _warn(context, "  Vendor issuer URL: %s", claims.get("iss", "<missing>"))
    _warn(context, "  Vendor JWT KID: %s", header.get("kid", "<missing>"))
    _warn(
        context,
        "  Vendor JWT header: %s",
        json.dumps(header, sort_keys=True, default=str),
    )
    _warn(
        context,
        "  Vendor JWT claims: %s",
        json.dumps(claims, sort_keys=True, default=str),
    )


class OidcProvider(CredentialProvider):
    """Resolves credentials via OIDC auto-discovery.

    Requires a Workspace and CLOUDSMITH_SERVICE_SLUG to be set (via environment
    variables or Click options). Auto-detects the environment, fetches the
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

        org = context.org
        service_slug = context.oidc_service_slug

        if not org or not service_slug:
            if context.debug:
                logger.debug(
                    "OidcProvider: CLOUDSMITH_WORKSPACE (or CLOUDSMITH_ORG) "
                    "and/or CLOUDSMITH_SERVICE_SLUG "
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
                auth_type="bearer",
            )

        from ..oidc.detectors import detect_environment
        from ..oidc.exchange import OidcExchangeError, exchange_oidc_token

        detector = detect_environment(context=context)
        if detector is None:
            if context.debug:
                logger.debug(
                    "OidcProvider: No supported OIDC environment detected, skipping"
                )
            return None

        try:
            vendor_token = detector.get_token()
        except Exception:  # pylint: disable=broad-exception-caught
            _warn(
                context,
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
            _warn(
                context,
                "OIDC: %s detector returned an empty token.",
                detector.name,
            )
            return None

        try:
            cloudsmith_token = exchange_oidc_token(
                context=context,
                org=org,
                service_slug=service_slug,
                oidc_token=vendor_token,
            )
        except OidcExchangeError as exc:
            _warn(context, "OIDC: Token exchange failed: %s", exc)
            _log_exchange_diagnostics(
                context=context,
                detector_name=detector.name,
                org=org,
                service_slug=service_slug,
                vendor_token=vendor_token,
            )
            return None
        except Exception:  # pylint: disable=broad-exception-caught
            _warn(
                context,
                "OIDC: Token exchange failed unexpectedly. Use --debug for details.",
            )
            logger.debug("OidcProvider: OIDC token exchange error", exc_info=True)
            _log_exchange_diagnostics(
                context=context,
                detector_name=detector.name,
                org=org,
                service_slug=service_slug,
                vendor_token=vendor_token,
            )
            return None

        if not cloudsmith_token:
            return None

        store_cached_token(context.api_host, org, service_slug, cloudsmith_token)

        return CredentialResult(
            api_key=cloudsmith_token,
            source_name="oidc",
            source_detail=f"OIDC via {detector.name} (org: {org}, service: {service_slug})",
            auth_type="bearer",
        )
