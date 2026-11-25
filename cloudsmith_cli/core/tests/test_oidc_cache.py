"""Tests for the OIDC token cache."""

import json
import time
from unittest.mock import patch

import jwt
import pytest

from cloudsmith_cli.core.credentials.oidc import cache

API_HOST = "https://api.cloudsmith.io"


def _token() -> str:
    return jwt.encode({"exp": time.time() + 3600}, key="", algorithm="none")


@pytest.fixture()
def disk_only(tmp_path):
    """Use a cache directory in tmp_path, with no keyring."""
    with (
        patch(
            "cloudsmith_cli.cli.config.get_default_config_path",
            return_value=str(tmp_path),
        ),
        patch.object(cache, "_store_in_keyring", return_value=False),
        patch.object(cache, "_get_from_keyring", return_value=None),
    ):
        yield tmp_path


def test_disk_cache_keeps_the_vendor(disk_only):
    """A token cached on disk comes back with the name of the CI vendor."""
    token = _token()
    cache.store_cached_token(
        API_HOST, "acme", "ci-service", token, detector="GitHub Actions"
    )

    assert cache.get_cached_token(API_HOST, "acme", "ci-service") == (
        cache.CachedToken(token, detector="GitHub Actions")
    )


def test_disk_cache_entry_without_a_vendor(disk_only):
    """An entry that an older CLI wrote has no vendor name."""
    token = _token()
    cache.store_cached_token(API_HOST, "acme", "ci-service", token)

    assert cache.get_cached_token(API_HOST, "acme", "ci-service") == (
        cache.CachedToken(token)
    )


def test_keyring_cache_keeps_the_vendor():
    """A token cached in the keyring comes back with the name of the CI vendor."""
    token = _token()
    entry = json.dumps(
        {"token": token, "expires_at": time.time() + 3600, "detector": "CircleCI"}
    )

    with patch("cloudsmith_cli.core.keyring.get_oidc_token", return_value=entry):
        assert cache.get_cached_token(API_HOST, "acme", "ci-service") == (
            cache.CachedToken(token, detector="CircleCI")
        )
