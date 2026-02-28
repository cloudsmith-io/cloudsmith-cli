"""
Shared utilities for credential helpers.

Provides credential resolution and domain checking used by all helpers.
Networking configuration (proxy, TLS, headers) is read from the same
environment variables and config files used by the main CLI so that
credential helpers work correctly behind proxies and with custom certs.
"""

import logging
import os

from ..core.credentials import CredentialContext, CredentialProviderChain

logger = logging.getLogger(__name__)


def _get_networking_config():
    """Read networking configuration from env vars and the CLI config file.

    Sources (in priority order):
        1. Environment variables: CLOUDSMITH_API_PROXY,
           CLOUDSMITH_WITHOUT_API_SSL_VERIFY, CLOUDSMITH_API_USER_AGENT,
           CLOUDSMITH_API_HEADERS
        2. CLI config file (config.ini): api_proxy, api_ssl_verify

    Returns:
        dict with keys: proxy, ssl_verify, user_agent, headers
    """
    proxy = os.environ.get("CLOUDSMITH_API_PROXY", "").strip() or None
    user_agent = os.environ.get("CLOUDSMITH_API_USER_AGENT", "").strip() or None

    # SSL verify: env var is an opt-out flag (presence means disable)
    ssl_verify_env = os.environ.get("CLOUDSMITH_WITHOUT_API_SSL_VERIFY", "").strip()
    ssl_verify = (
        not ssl_verify_env.lower() in ("1", "true", "yes") if ssl_verify_env else True
    )

    # Parse extra headers from CSV "key=value,key2=value2"
    headers = None
    headers_env = os.environ.get("CLOUDSMITH_API_HEADERS", "").strip()
    if headers_env:
        headers = {}
        for pair in headers_env.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                headers[k.strip()] = v.strip()

    # Fall back to CLI config file for proxy and ssl_verify
    if not proxy or ssl_verify is True:
        try:
            from ..cli.config import ConfigReader

            raw_config = ConfigReader.read_config()
            defaults = raw_config.get("default", {})

            if not proxy:
                cfg_proxy = defaults.get("api_proxy", "").strip()
                if cfg_proxy:
                    proxy = cfg_proxy

            # Only override ssl_verify if the env var wasn't explicitly set
            if not ssl_verify_env:
                cfg_ssl = defaults.get("api_ssl_verify", "true").strip().lower()
                if cfg_ssl in ("0", "false", "no"):
                    ssl_verify = False
        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug("Failed to read CLI config for networking", exc_info=True)

    return {
        "proxy": proxy,
        "ssl_verify": ssl_verify,
        "user_agent": user_agent,
        "headers": headers,
    }


def resolve_credentials(debug=False):
    """
    Resolve Cloudsmith credentials using the provider chain.

    Tries providers in order: environment variables, config file, keyring, OIDC.
    Networking configuration is read from env vars and the CLI config file so
    that OIDC token exchange works behind proxies.

    Args:
        debug: Enable debug logging

    Returns:
        CredentialResult with .api_key, or None if no credentials available
    """
    api_host = os.environ.get("CLOUDSMITH_API_HOST", "https://api.cloudsmith.io")
    net = _get_networking_config()

    context = CredentialContext(
        api_host=api_host,
        debug=debug,
        proxy=net["proxy"],
        ssl_verify=net["ssl_verify"],
        user_agent=net["user_agent"],
        headers=net["headers"],
    )

    chain = CredentialProviderChain()
    result = chain.resolve(context)

    if not result or not result.api_key:
        return None

    return result


def extract_hostname(url):
    """
    Extract bare hostname from any URL format.

    Handles protocols, sparse+ prefix, ports, paths, and trailing slashes.

    Args:
        url: URL in any format (e.g., "sparse+https://cargo.cloudsmith.io/org/repo/")

    Returns:
        str: Lowercase hostname (e.g., "cargo.cloudsmith.io")
    """
    if not url:
        return ""

    normalized = url.lower().strip()

    # Remove sparse+ prefix (Cargo)
    if normalized.startswith("sparse+"):
        normalized = normalized[7:]

    # Remove protocol
    if "://" in normalized:
        normalized = normalized.split("://", 1)[1]

    # Remove userinfo (user@host)
    if "@" in normalized.split("/")[0]:
        normalized = normalized.split("@", 1)[1]

    # Extract hostname (before first / or :)
    hostname = normalized.split("/")[0].split(":")[0]

    return hostname


def is_cloudsmith_domain(url, _credential_result=None):
    """
    Check if a URL points to a Cloudsmith service.

    Checks standard *.cloudsmith.io domains first (no auth needed).
    If not a standard domain, uses the provided credential result (or
    resolves credentials) and queries the Cloudsmith API for custom domains.

    Args:
        url: URL or hostname to check
        _credential_result: Pre-resolved CredentialResult to avoid duplicate
            credential resolution. If None, resolves credentials internally.

    Returns:
        bool: True if this is a Cloudsmith domain
    """
    hostname = extract_hostname(url)
    if not hostname:
        return False

    # Standard Cloudsmith domains — no auth needed
    if hostname.endswith("cloudsmith.io") or hostname == "cloudsmith.io":
        return True

    # Custom domains require org + auth
    org = os.environ.get("CLOUDSMITH_ORG", "").strip()
    if not org:
        return False

    result = _credential_result or resolve_credentials()
    if not result:
        return False

    from .custom_domains import get_custom_domains_for_org

    api_host = os.environ.get("CLOUDSMITH_API_HOST", "https://api.cloudsmith.io")
    net = _get_networking_config()
    custom_domains = get_custom_domains_for_org(
        org,
        api_host,
        result.api_key,
        proxy=net["proxy"],
        ssl_verify=net["ssl_verify"],
        user_agent=net["user_agent"],
        headers=net["headers"],
    )

    return hostname in [d.lower() for d in custom_domains]
