"""Tests for shared SSO session renewal."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import jwt
import requests
from freezegun import freeze_time

from cloudsmith_cli.core.api.exceptions import ApiException
from cloudsmith_cli.core.sso import renew_sso_session

API_HOST = "https://api.example.com"


def test_successful_renewal_stores_rotated_tokens():
    with (
        patch(
            "cloudsmith_cli.core.sso.keyring.get_access_token",
            return_value="old-access",
        ),
        patch(
            "cloudsmith_cli.core.sso.keyring.get_refresh_token",
            return_value="old-refresh",
        ),
        patch(
            "cloudsmith_cli.core.sso.refresh_access_token",
            return_value=("new-access", "new-refresh"),
        ),
        patch("cloudsmith_cli.core.sso.keyring.store_sso_tokens") as store,
    ):
        result = renew_sso_session(API_HOST, MagicMock(), profile="work")

    assert (result.status, result.access_token) == ("renewed", "new-access")
    store.assert_called_once_with(API_HOST, "new-access", "new-refresh", profile="work")


@freeze_time("2024-06-01 10:00:00")
def test_transient_failure_reuses_usable_access_token():
    access_token = jwt.encode(
        {"exp": datetime(2024, 6, 1, 9, 59, 31, tzinfo=timezone.utc)},
        "not-used-for-verification",
        algorithm="HS256",
    )
    error = requests.ConnectionError("offline")
    with (
        patch(
            "cloudsmith_cli.core.sso.keyring.get_access_token",
            return_value=access_token,
        ),
        patch(
            "cloudsmith_cli.core.sso.keyring.get_refresh_token",
            return_value="old-refresh",
        ),
        patch("cloudsmith_cli.core.sso.refresh_access_token", side_effect=error),
        patch(
            "cloudsmith_cli.core.sso.keyring.update_refresh_attempted_at"
        ) as attempted,
    ):
        result = renew_sso_session(API_HOST, MagicMock(), profile="work")

    assert (result.status, result.access_token, result.error) == (
        "current",
        access_token,
        error,
    )
    attempted.assert_called_once_with(API_HOST, profile="work")


def test_rejected_renewal_reuses_concurrently_rotated_tokens():
    with (
        patch(
            "cloudsmith_cli.core.sso.keyring.get_access_token",
            side_effect=["old-access", "new-access"],
        ),
        patch(
            "cloudsmith_cli.core.sso.keyring.get_refresh_token",
            side_effect=["old-refresh", "new-refresh"],
        ),
        patch(
            "cloudsmith_cli.core.sso.refresh_access_token",
            side_effect=ApiException(400, detail="Already rotated"),
        ),
        patch("cloudsmith_cli.core.sso.keyring.delete_sso_tokens") as delete,
    ):
        result = renew_sso_session(API_HOST, MagicMock())

    assert (result.status, result.access_token) == ("current", "new-access")
    delete.assert_not_called()


def test_definitive_rejection_cleans_up_profile_then_legacy_tokens():
    with (
        patch(
            "cloudsmith_cli.core.sso.keyring.get_access_token",
            return_value="old-access",
        ),
        patch(
            "cloudsmith_cli.core.sso.keyring.get_refresh_token",
            return_value="old-refresh",
        ),
        patch(
            "cloudsmith_cli.core.sso.refresh_access_token",
            side_effect=ApiException(401, detail="Rejected"),
        ),
        patch(
            "cloudsmith_cli.core.sso.keyring.delete_sso_tokens",
            side_effect=[False, True],
        ) as delete,
    ):
        result = renew_sso_session(API_HOST, MagicMock(), profile="work")

    assert result.status == "rejected"
    assert delete.call_args_list == [
        call(API_HOST, profile="work", include_legacy=False),
        call(API_HOST),
    ]
