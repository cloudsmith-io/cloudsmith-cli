"""OIDC token cache.

Caches Cloudsmith API tokens obtained via OIDC exchange to avoid unnecessary
re-exchanges. Uses system keyring when available (respecting CLOUDSMITH_NO_KEYRING),
with automatic fallback to filesystem storage when keyring is unavailable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

EXPIRY_MARGIN_SECONDS = 60

_CACHE_DIR_NAME = "oidc_token_cache"


def _get_cache_dir() -> str:
    """Return the cache directory path, creating it if needed."""
    from ....cli.config import get_default_config_path

    base = get_default_config_path()
    cache_dir = os.path.join(base, _CACHE_DIR_NAME)
    if not os.path.isdir(cache_dir):
        os.makedirs(cache_dir, mode=0o700, exist_ok=True)
    return cache_dir


def _cache_key(api_host: str, org: str, service_slug: str) -> str:
    """Compute a deterministic cache filename from the exchange parameters."""
    raw = f"{api_host}|{org}|{service_slug}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return f"oidc_{digest}.json"


def _decode_jwt_exp(token: str) -> float | None:
    """Decode the exp claim from a JWT without verification."""
    try:
        import jwt

        payload = jwt.decode(
            token,
            options={"verify_signature": False},
            algorithms=["RS256", "ES256", "HS256"],
        )
        exp = payload.get("exp")
        if exp is not None:
            return float(exp)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.debug("Failed to decode JWT expiry", exc_info=True)
    return None


def get_cached_token(api_host: str, org: str, service_slug: str) -> str | None:
    """Return a cached token if it exists and is not expired."""
    token = _get_from_keyring(api_host, org, service_slug)
    if token:
        return token
    return _get_from_disk(api_host, org, service_slug)


def _get_from_keyring(api_host: str, org: str, service_slug: str) -> str | None:
    """Try to get token from keyring."""
    try:
        from ...keyring import get_oidc_token

        token_data = get_oidc_token(api_host, org, service_slug)
        if not token_data:
            return None

        data = json.loads(token_data)
        token = data.get("token")
        expires_at = data.get("expires_at")

        if not token:
            return None

        if expires_at is not None:
            remaining = expires_at - time.time()
            if remaining < EXPIRY_MARGIN_SECONDS:
                logger.debug(
                    "Keyring OIDC token expired or expiring soon "
                    "(%.0fs remaining, margin=%ds)",
                    remaining,
                    EXPIRY_MARGIN_SECONDS,
                )
                from ...keyring import delete_oidc_token

                delete_oidc_token(api_host, org, service_slug)
                return None
            logger.debug("Using keyring OIDC token (expires in %.0fs)", remaining)
        else:
            logger.debug("Using keyring OIDC token (no expiry information)")

        return token

    except Exception:  # pylint: disable=broad-exception-caught
        logger.debug("Failed to read OIDC token from keyring", exc_info=True)
        return None


def _get_from_disk(api_host: str, org: str, service_slug: str) -> str | None:
    """Try to get token from disk cache."""
    cache_dir = _get_cache_dir()
    cache_file = os.path.join(cache_dir, _cache_key(api_host, org, service_slug))

    if not os.path.isfile(cache_file):
        return None

    try:
        with open(cache_file) as f:
            data = json.load(f)

        token = data.get("token")
        expires_at = data.get("expires_at")

        if not token:
            return None

        if expires_at is not None:
            remaining = expires_at - time.time()
            if remaining < EXPIRY_MARGIN_SECONDS:
                logger.debug(
                    "Disk cached OIDC token expired or expiring soon "
                    "(%.0fs remaining, margin=%ds)",
                    remaining,
                    EXPIRY_MARGIN_SECONDS,
                )
                _remove_cache_file(cache_file)
                return None
            logger.debug("Using disk cached OIDC token (expires in %.0fs)", remaining)
        else:
            logger.debug("Using disk cached OIDC token (no expiry information)")

        return token

    except (json.JSONDecodeError, OSError, KeyError):
        logger.debug("Failed to read OIDC token from disk cache", exc_info=True)
        _remove_cache_file(cache_file)
        return None


def store_cached_token(api_host: str, org: str, service_slug: str, token: str) -> None:
    """Cache a token in keyring (if available) or filesystem."""
    expires_at = _decode_jwt_exp(token)

    data = {
        "token": token,
        "expires_at": expires_at,
        "api_host": api_host,
        "org": org,
        "service_slug": service_slug,
        "cached_at": time.time(),
    }

    if _store_in_keyring(api_host, org, service_slug, data):
        return

    _store_on_disk(api_host, org, service_slug, data)


def _store_in_keyring(api_host: str, org: str, service_slug: str, data: dict) -> bool:
    """Try to store token in keyring."""
    try:
        from ...keyring import store_oidc_token

        token_data = json.dumps(data)
        success = store_oidc_token(api_host, org, service_slug, token_data)
        if success:
            logger.debug(
                "Stored OIDC token in keyring (expires_at=%s)", data.get("expires_at")
            )
        return success
    except Exception:  # pylint: disable=broad-exception-caught
        logger.debug("Failed to store OIDC token in keyring", exc_info=True)
        return False


def _store_on_disk(api_host: str, org: str, service_slug: str, data: dict) -> None:
    """Store token on disk."""
    cache_dir = _get_cache_dir()
    cache_file = os.path.join(cache_dir, _cache_key(api_host, org, service_slug))

    try:
        fd = os.open(cache_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        logger.debug(
            "Stored OIDC token on disk (expires_at=%s)", data.get("expires_at")
        )
    except OSError:
        logger.debug("Failed to write OIDC token to disk cache", exc_info=True)


def invalidate_cached_token(api_host: str, org: str, service_slug: str) -> None:
    """Remove a cached token from both keyring and disk."""
    try:
        from ...keyring import delete_oidc_token

        delete_oidc_token(api_host, org, service_slug)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.debug("Failed to delete OIDC token from keyring", exc_info=True)

    cache_dir = _get_cache_dir()
    cache_file = os.path.join(cache_dir, _cache_key(api_host, org, service_slug))
    _remove_cache_file(cache_file)


def _remove_cache_file(path: str) -> None:
    """Safely remove a cache file."""
    try:
        os.unlink(path)
    except (OSError, TypeError):
        pass
