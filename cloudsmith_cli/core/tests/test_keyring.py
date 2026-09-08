import getpass
import importlib
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, Mock, call, patch

import jwt
import pytest
from freezegun import freeze_time
from keyrings.cryptfile.cryptfile import CryptFileKeyring

from .. import keyring as core_keyring
from ..keyring import (
    delete_sso_tokens,
    get_access_token,
    get_refresh_attempted_at,
    get_refresh_token,
    has_sso_tokens,
    should_refresh_access_token,
    should_use_keyring,
    store_access_token,
    store_refresh_token,
    store_sso_tokens,
    update_refresh_attempted_at,
)


@pytest.fixture
def mock_get_user():
    with patch.object(getpass, "getuser", return_value="test_user") as get_user_mock:
        yield get_user_mock


@pytest.fixture
def mock_get_password():
    import keyring

    with patch.object(keyring, "get_password") as get_password_mock:
        yield get_password_mock


@pytest.fixture
def mock_set_password():
    import keyring

    with patch.object(keyring, "set_password") as set_password_mock:
        yield set_password_mock


@pytest.fixture
def mock_delete_password():
    import keyring

    with patch.object(keyring, "delete_password") as delete_password_mock:
        yield delete_password_mock


@pytest.fixture(autouse=True)
def mock_get_keyring():
    import keyring

    with patch.object(keyring, "get_keyring") as get_keyring_mock:
        yield get_keyring_mock


class TestKeyring:
    api_host = "https://example.com"

    def test_store_access_token(self, mock_get_user, mock_set_password):
        store_access_token(self.api_host, "access_token")

        mock_set_password.assert_called_once_with(
            "cloudsmith_cli-access_token-https://example.com",
            "test_user",
            "access_token",
        )

    def test_get_access_token(self, mock_get_user, mock_get_password):
        mock_get_password.return_value = "access_token"

        assert get_access_token(self.api_host) == "access_token"
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token-https://example.com", "test_user"
        )

    def test_get_access_token_when_error_raised(self, mock_get_user, mock_get_password):
        from keyring.errors import KeyringError

        mock_get_password.side_effect = KeyringError("A keyring error occurred")

        assert get_access_token(self.api_host) is None
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token-https://example.com", "test_user"
        )

    @freeze_time("2024-06-01 10:00:00")
    def test_update_refresh_attempted_at(self, mock_get_user, mock_set_password):
        attempted_at = datetime.now(tz=timezone.utc).isoformat()

        update_refresh_attempted_at(self.api_host)

        mock_set_password.assert_called_once_with(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com",
            "test_user",
            attempted_at,
        )

    def test_get_refresh_attempted_at(self, mock_get_user, mock_get_password):
        mock_get_password.return_value = datetime(
            2024, 6, 1, 10, 0, tzinfo=timezone.utc
        ).isoformat()

        assert get_refresh_attempted_at(self.api_host) == datetime(
            2024, 6, 1, hour=10, minute=0, tzinfo=timezone.utc
        )
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com",
            "test_user",
        )

    def test_get_refresh_attempted_at_when_keyring_error_raised(
        self, mock_get_user, mock_get_password
    ):
        from keyring.errors import KeyringError

        mock_get_password.side_effect = KeyringError("A keyring error occurred")

        assert get_refresh_attempted_at(self.api_host) is None
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com",
            "test_user",
        )

    def test_get_refresh_attempted_at_when_invalid_datetime_returned(
        self, mock_get_user, mock_get_password
    ):
        mock_get_password.return_value = "invalid_datetime"

        assert get_refresh_attempted_at(self.api_host) is None
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com",
            "test_user",
        )

    @freeze_time("2024-06-01 10:00:00")
    def test_should_refresh_access_token_with_new_token(
        self, mock_get_user, mock_get_password
    ):
        mock_get_password.return_value = datetime.now(tz=timezone.utc).isoformat()

        assert not should_refresh_access_token(self.api_host)
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com",
            "test_user",
        )

    @freeze_time("2024-06-01 10:00:00")
    def test_should_refresh_access_token_with_token_about_to_expire(
        self, mock_get_user, mock_get_password
    ):
        mock_get_password.return_value = (
            datetime.now(tz=timezone.utc) - timedelta(minutes=30)
        ).isoformat()

        assert not should_refresh_access_token(self.api_host)
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com",
            "test_user",
        )

    @freeze_time("2024-06-01 10:00:00")
    def test_should_refresh_access_token_with_expired_token(
        self, mock_get_user, mock_get_password
    ):
        mock_get_password.return_value = (
            datetime.now(tz=timezone.utc) - timedelta(minutes=31)
        ).isoformat()

        assert should_refresh_access_token(self.api_host)
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com",
            "test_user",
        )

    @freeze_time("2024-06-01 10:00:00")
    @pytest.mark.parametrize(
        "expires_at,attempted_at,expected",
        [
            ("2024-06-01 10:31:00", None, False),
            ("2024-06-01 10:30:00", None, True),
            ("2024-06-01 09:59:00", "2024-06-01T09:59:00+00:00", True),
        ],
    )
    def test_jwt_refresh_uses_expiry_and_ignores_throttle_after_expiration(
        self, mock_get_password, expires_at, attempted_at, expected
    ):
        mock_get_password.return_value = attempted_at
        access_token = jwt.encode(
            {"exp": datetime.fromisoformat(expires_at).replace(tzinfo=timezone.utc)},
            "not-used-for-verification",
            algorithm="HS256",
        )

        assert (
            should_refresh_access_token(self.api_host, access_token=access_token)
            is expected
        )

    def test_store_refresh_token(self, mock_get_user, mock_set_password):
        store_refresh_token(self.api_host, "refresh_token")

        mock_set_password.assert_called_once_with(
            "cloudsmith_cli-refresh_token-https://example.com",
            "test_user",
            "refresh_token",
        )

    def test_get_refresh_token(self, mock_get_user, mock_get_password):
        mock_get_password.return_value = "refresh_token"

        assert get_refresh_token(self.api_host) == "refresh_token"
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-refresh_token-https://example.com", "test_user"
        )

    def test_get_refresh_token_when_error_raised(
        self, mock_get_user, mock_get_password
    ):
        from keyring.errors import KeyringError

        mock_get_password.side_effect = KeyringError("A keyring error occurred")

        assert get_refresh_token(self.api_host) is None
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-refresh_token-https://example.com", "test_user"
        )

    @freeze_time("2024-06-01 10:00:00")
    def test_store_sso_tokens(self, mock_get_user, mock_set_password):
        # Ensure keyring is enabled
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with patch.dict(os.environ, env, clear=True):
            result = store_sso_tokens(self.api_host, "access_token", "refresh_token")

        assert result is True
        refresh_key = (
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com"
        )
        assert mock_set_password.call_args_list == [
            call(
                "cloudsmith_cli-refresh_token-https://example.com",
                "test_user",
                "refresh_token",
            ),
            call(
                "cloudsmith_cli-access_token-https://example.com",
                "test_user",
                "access_token",
            ),
            call(refresh_key, "test_user", ANY),
        ]

    def test_store_sso_tokens_returns_false_when_keyring_disabled(
        self, mock_get_user, mock_set_password
    ):
        """Verify store_sso_tokens returns False when keyring disabled."""
        with patch.dict(os.environ, {"CLOUDSMITH_NO_KEYRING": "1"}):
            result = store_sso_tokens(self.api_host, "access_token", "refresh_token")

        assert result is False
        mock_set_password.assert_not_called()


class TestProfileScopedKeys:
    """Tests for profile-scoped keyring service names."""

    api_host = "https://example.com"

    def test_store_access_token_with_profile(self, mock_get_user, mock_set_password):
        store_access_token(self.api_host, "access_token", profile="staging")

        mock_set_password.assert_called_once_with(
            "cloudsmith_cli-access_token-https://example.com-profile-staging",
            "test_user",
            "access_token",
        )

    def test_store_access_token_with_default_profile_uses_legacy_key(
        self, mock_get_user, mock_set_password
    ):
        store_access_token(self.api_host, "access_token", profile="default")

        mock_set_password.assert_called_once_with(
            "cloudsmith_cli-access_token-https://example.com",
            "test_user",
            "access_token",
        )

    def test_get_access_token_with_profile(self, mock_get_user, mock_get_password):
        mock_get_password.return_value = "access_token"

        assert get_access_token(self.api_host, profile="staging") == "access_token"
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token-https://example.com-profile-staging",
            "test_user",
        )

    def test_get_refresh_token_with_profile(self, mock_get_user, mock_get_password):
        mock_get_password.return_value = "refresh_token"

        assert get_refresh_token(self.api_host, profile="staging") == "refresh_token"
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-refresh_token-https://example.com-profile-staging",
            "test_user",
        )

    @freeze_time("2024-06-01 10:00:00")
    def test_store_sso_tokens_with_profile(self, mock_get_user, mock_set_password):
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with patch.dict(os.environ, env, clear=True):
            result = store_sso_tokens(
                self.api_host, "access_token", "refresh_token", profile="staging"
            )

        assert result is True
        assert mock_set_password.call_count == 3
        mock_set_password.assert_any_call(
            "cloudsmith_cli-access_token-https://example.com-profile-staging",
            "test_user",
            "access_token",
        )
        mock_set_password.assert_any_call(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com"
            "-profile-staging",
            "test_user",
            ANY,
        )
        mock_set_password.assert_any_call(
            "cloudsmith_cli-refresh_token-https://example.com-profile-staging",
            "test_user",
            "refresh_token",
        )

    def test_has_sso_tokens_with_profile(self, mock_get_user, mock_get_password):
        mock_get_password.return_value = "some_token"

        assert has_sso_tokens(self.api_host, profile="staging") is True
        first_key = mock_get_password.call_args_list[0].args[0]
        assert first_key == (
            "cloudsmith_cli-access_token-https://example.com-profile-staging"
        )

    def test_delete_sso_tokens_with_profile_removes_legacy_entries(
        self, mock_get_user, mock_delete_password
    ):
        assert delete_sso_tokens(self.api_host, profile="staging") is True

        deleted_keys = [call.args[0] for call in mock_delete_password.call_args_list]
        assert deleted_keys == [
            "cloudsmith_cli-access_token-https://example.com-profile-staging",
            "cloudsmith_cli-refresh_token-https://example.com-profile-staging",
            (
                "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com"
                "-profile-staging"
            ),
            "cloudsmith_cli-access_token-https://example.com",
            "cloudsmith_cli-refresh_token-https://example.com",
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com",
        ]

    def test_delete_sso_tokens_without_legacy_keeps_unscoped_entries(
        self, mock_get_user, mock_delete_password
    ):
        assert (
            delete_sso_tokens(self.api_host, profile="staging", include_legacy=False)
            is True
        )

        deleted_keys = [call.args[0] for call in mock_delete_password.call_args_list]
        assert deleted_keys == [
            "cloudsmith_cli-access_token-https://example.com-profile-staging",
            "cloudsmith_cli-refresh_token-https://example.com-profile-staging",
            (
                "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com"
                "-profile-staging"
            ),
        ]

    def test_get_access_token_with_profile_falls_back_to_legacy_key(
        self, mock_get_user, mock_get_password
    ):
        mock_get_password.side_effect = [None, "legacy_token"]

        assert get_access_token(self.api_host, profile="staging") == "legacy_token"
        requested_keys = [call.args[0] for call in mock_get_password.call_args_list]
        assert requested_keys == [
            "cloudsmith_cli-access_token-https://example.com-profile-staging",
            "cloudsmith_cli-access_token-https://example.com",
        ]

    def test_get_access_token_with_default_profile_does_not_fall_back(
        self, mock_get_user, mock_get_password
    ):
        mock_get_password.return_value = None

        assert get_access_token(self.api_host, profile="default") is None
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token-https://example.com", "test_user"
        )

    def test_get_refresh_token_with_profile_falls_back_to_legacy_key(
        self, mock_get_user, mock_get_password
    ):
        mock_get_password.side_effect = [None, "legacy_refresh"]

        assert get_refresh_token(self.api_host, profile="staging") == "legacy_refresh"
        requested_keys = [call.args[0] for call in mock_get_password.call_args_list]
        assert requested_keys == [
            "cloudsmith_cli-refresh_token-https://example.com-profile-staging",
            "cloudsmith_cli-refresh_token-https://example.com",
        ]

    @freeze_time("2024-06-01 10:00:00")
    def test_should_refresh_access_token_with_profile(
        self, mock_get_user, mock_get_password
    ):
        mock_get_password.return_value = (
            datetime.now(tz=timezone.utc) - timedelta(minutes=31)
        ).isoformat()

        assert should_refresh_access_token(self.api_host, profile="staging")
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com"
            "-profile-staging",
            "test_user",
        )


def test_macos_keychain_imports_on_every_platform():
    """The binary build imports every bundled module on Linux."""
    module = importlib.import_module("cloudsmith_cli.core.macos_keychain")
    result = module.update_generic_password(
        "cloudsmith_cli-import-check", "nobody", "value"
    )
    assert result is False


class FakeMacosBackend:
    pass


FakeMacosBackend.__module__ = "keyring.backends.macOS"


class FakeChainerBackend:
    def __init__(self, backends):
        self.backends = backends


class TestUpdateKeychainItemInPlace:
    """Tests for the in-place update path that keeps the access control list."""

    api_host = "https://example.com"

    def test_set_value_skips_set_password_when_update_succeeds(
        self, mock_get_user, mock_set_password
    ):
        with patch.object(
            core_keyring, "_update_keychain_item_in_place", return_value=True
        ):
            store_access_token(self.api_host, "access_token")
        mock_set_password.assert_not_called()

    def test_set_value_falls_back_when_update_fails(
        self, mock_get_user, mock_set_password
    ):
        with patch.object(
            core_keyring, "_update_keychain_item_in_place", return_value=False
        ):
            store_access_token(self.api_host, "access_token")
        mock_set_password.assert_called_once_with(
            "cloudsmith_cli-access_token-https://example.com",
            "test_user",
            "access_token",
        )

    def test_update_returns_false_off_macos(self, mock_get_keyring):
        importer = Mock()
        with (
            patch("sys.platform", "linux"),
            patch.object(core_keyring, "_import_macos_keychain", importer),
        ):
            result = core_keyring._update_keychain_item_in_place(
                "service", "user", "value"
            )
        assert result is False
        importer.assert_not_called()

    def test_update_returns_false_for_non_macos_backend(self, mock_get_keyring):
        importer = Mock()
        with (
            patch("sys.platform", "darwin"),
            patch.object(core_keyring, "_import_macos_keychain", importer),
        ):
            result = core_keyring._update_keychain_item_in_place(
                "service", "user", "value"
            )
        assert result is False
        importer.assert_not_called()

    def test_update_uses_macos_module_for_macos_backend(self, mock_get_keyring):
        mock_get_keyring.return_value = FakeMacosBackend()
        macos_module = Mock()
        macos_module.update_generic_password.return_value = True
        with (
            patch("sys.platform", "darwin"),
            patch.object(
                core_keyring, "_import_macos_keychain", return_value=macos_module
            ),
        ):
            result = core_keyring._update_keychain_item_in_place(
                "service", "user", "value"
            )
        assert result is True
        macos_module.update_generic_password.assert_called_once_with(
            "service", "user", "value"
        )

    def test_update_uses_macos_module_when_chainer_delegates_to_macos(
        self, mock_get_keyring
    ):
        mock_get_keyring.return_value = FakeChainerBackend([FakeMacosBackend(), Mock()])
        macos_module = Mock()
        macos_module.update_generic_password.return_value = True
        with (
            patch("sys.platform", "darwin"),
            patch.object(
                core_keyring, "_import_macos_keychain", return_value=macos_module
            ),
        ):
            result = core_keyring._update_keychain_item_in_place(
                "service", "user", "value"
            )
        assert result is True
        macos_module.update_generic_password.assert_called_once_with(
            "service", "user", "value"
        )

    def test_update_returns_false_when_chainer_prefers_other_backend(
        self, mock_get_keyring
    ):
        mock_get_keyring.return_value = FakeChainerBackend([Mock(), FakeMacosBackend()])
        importer = Mock()
        with (
            patch("sys.platform", "darwin"),
            patch.object(core_keyring, "_import_macos_keychain", importer),
        ):
            result = core_keyring._update_keychain_item_in_place(
                "service", "user", "value"
            )
        assert result is False
        importer.assert_not_called()

    def test_update_returns_false_when_module_unavailable(self, mock_get_keyring):
        mock_get_keyring.return_value = FakeMacosBackend()
        with (
            patch("sys.platform", "darwin"),
            patch.object(core_keyring, "_import_macos_keychain", return_value=None),
        ):
            result = core_keyring._update_keychain_item_in_place(
                "service", "user", "value"
            )
        assert result is False


class TestShouldUseKeyring:
    """Tests for the should_use_keyring function."""

    def test_returns_true_by_default(self):
        """When env var is not set, keyring should be used."""
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with patch.dict(os.environ, env, clear=True):
            assert should_use_keyring() is True

    @pytest.mark.parametrize(
        "env_value", ["1", "true", "True", "TRUE", "yes", "Yes", "YES"]
    )
    def test_returns_false_when_env_var_is_truthy(self, env_value):
        """Keyring should not be used when CLOUDSMITH_NO_KEYRING is truthy."""
        with patch.dict(os.environ, {"CLOUDSMITH_NO_KEYRING": env_value}):
            assert should_use_keyring() is False

    @pytest.mark.parametrize("env_value", ["0", "false", "False", "no", "No", ""])
    def test_returns_true_when_env_var_is_falsy(self, env_value):
        """Keyring should be used when CLOUDSMITH_NO_KEYRING is falsy."""
        with patch.dict(os.environ, {"CLOUDSMITH_NO_KEYRING": env_value}):
            assert should_use_keyring() is True


class TestKeyringBackendAlias:
    """Tests for CLOUDSMITH_KEYRING_BACKEND aliasing PYTHON_KEYRING_BACKEND."""

    api_host = "https://example.com"

    def test_sets_python_keyring_backend_when_unset(
        self, mock_get_user, mock_get_password
    ):
        env = os.environ.copy()
        env.pop("PYTHON_KEYRING_BACKEND", None)
        env["CLOUDSMITH_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert (
                os.environ["PYTHON_KEYRING_BACKEND"] == "keyring.backends.null.Keyring"
            )

    def test_does_not_override_existing_python_keyring_backend(
        self, mock_get_user, mock_get_password
    ):
        env = os.environ.copy()
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.SecretService.Keyring"
        env["CLOUDSMITH_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert (
                os.environ["PYTHON_KEYRING_BACKEND"]
                == "keyring.backends.SecretService.Keyring"
            )

    def test_no_op_when_alias_not_set(self, mock_get_user, mock_get_password):
        env = os.environ.copy()
        env.pop("PYTHON_KEYRING_BACKEND", None)
        env.pop("CLOUDSMITH_KEYRING_BACKEND", None)
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert "PYTHON_KEYRING_BACKEND" not in os.environ


class TestKeyringPropertyAlias:
    """Tests for CLOUDSMITH_KEYRING_KEY aliasing KEYRING_PROPERTY_KEYRING_KEY.

    keyrings.cryptfile and keyrings.alt override KeyringBackend.__init__
    without calling super(), so KEYRING_PROPERTY_* env vars never reach
    those backends via the library's own documented mechanism; we apply
    them ourselves by calling set_properties_from_env() on the resolved
    backend.
    """

    api_host = "https://example.com"

    def test_sets_keyring_property_when_unset(
        self, mock_get_user, mock_get_password, mock_get_keyring
    ):
        env = os.environ.copy()
        env.pop("KEYRING_PROPERTY_KEYRING_KEY", None)
        env["CLOUDSMITH_KEYRING_KEY"] = "super-secret"
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert os.environ["KEYRING_PROPERTY_KEYRING_KEY"] == "super-secret"

    def test_does_not_override_existing_keyring_property(
        self, mock_get_user, mock_get_password, mock_get_keyring
    ):
        env = os.environ.copy()
        env["KEYRING_PROPERTY_KEYRING_KEY"] = "native-secret"
        env["CLOUDSMITH_KEYRING_KEY"] = "alias-secret"
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert os.environ["KEYRING_PROPERTY_KEYRING_KEY"] == "native-secret"

    def test_no_op_when_alias_not_set(
        self, mock_get_user, mock_get_password, mock_get_keyring
    ):
        env = os.environ.copy()
        env.pop("KEYRING_PROPERTY_KEYRING_KEY", None)
        env.pop("CLOUDSMITH_KEYRING_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert "KEYRING_PROPERTY_KEYRING_KEY" not in os.environ

    def test_applies_properties_to_resolved_backend(
        self, mock_get_user, mock_get_password, mock_get_keyring
    ):
        get_access_token(self.api_host)
        mock_get_keyring.return_value.set_properties_from_env.assert_called_once()


class TestKeyringFilePathAlias:
    """Tests for CLOUDSMITH_KEYRING_FILE_PATH aliasing KEYRING_PROPERTY_FILE_PATH."""

    api_host = "https://example.com"

    def test_sets_keyring_property_when_unset(self, mock_get_user, mock_get_password):
        env = os.environ.copy()
        env.pop("KEYRING_PROPERTY_FILE_PATH", None)
        env["CLOUDSMITH_KEYRING_FILE_PATH"] = "/secure/path/keyring.cfg"
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert (
                os.environ["KEYRING_PROPERTY_FILE_PATH"] == "/secure/path/keyring.cfg"
            )

    def test_does_not_override_existing_keyring_property(
        self, mock_get_user, mock_get_password
    ):
        env = os.environ.copy()
        env["KEYRING_PROPERTY_FILE_PATH"] = "/native/path/keyring.cfg"
        env["CLOUDSMITH_KEYRING_FILE_PATH"] = "/alias/path/keyring.cfg"
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert (
                os.environ["KEYRING_PROPERTY_FILE_PATH"] == "/native/path/keyring.cfg"
            )

    def test_no_op_when_alias_not_set(self, mock_get_user, mock_get_password):
        env = os.environ.copy()
        env.pop("KEYRING_PROPERTY_FILE_PATH", None)
        env.pop("CLOUDSMITH_KEYRING_FILE_PATH", None)
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert "KEYRING_PROPERTY_FILE_PATH" not in os.environ

    def test_expands_user_and_env_vars(self, mock_get_user, mock_get_password):
        env = os.environ.copy()
        env.pop("KEYRING_PROPERTY_FILE_PATH", None)
        env["KEYRING_STORE_ROOT"] = "/secure"
        env["CLOUDSMITH_KEYRING_FILE_PATH"] = "$KEYRING_STORE_ROOT/keyring.cfg"
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert os.environ["KEYRING_PROPERTY_FILE_PATH"] == "/secure/keyring.cfg"

    def test_expands_home_directory(self, mock_get_user, mock_get_password):
        env = os.environ.copy()
        env.pop("KEYRING_PROPERTY_FILE_PATH", None)
        env["CLOUDSMITH_KEYRING_FILE_PATH"] = "~/keyring.cfg"
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert os.environ["KEYRING_PROPERTY_FILE_PATH"] == os.path.expanduser(
                "~/keyring.cfg"
            )

    def test_expands_home_inside_env_var_value(self, mock_get_user, mock_get_password):
        env = os.environ.copy()
        env.pop("KEYRING_PROPERTY_FILE_PATH", None)
        env["KEYRING_STORE_ROOT"] = "~"
        env["CLOUDSMITH_KEYRING_FILE_PATH"] = "$KEYRING_STORE_ROOT/keyring.cfg"
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert os.environ["KEYRING_PROPERTY_FILE_PATH"] == os.path.expanduser(
                "~/keyring.cfg"
            )


class TestKeyringDirEnv:
    """Tests for CLOUDSMITH_KEYRING_DIR redirecting file-backed backends."""

    api_host = "https://example.com"

    def test_sets_backend_file_path(
        self, mock_get_user, mock_get_password, mock_get_keyring
    ):
        backend = mock_get_keyring.return_value
        backend.filename = "cryptfile_pass.cfg"
        env = os.environ.copy()
        env.pop("KEYRING_PROPERTY_FILE_PATH", None)
        env["CLOUDSMITH_KEYRING_DIR"] = "/secure/dir"
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert backend.file_path == os.path.join(
                "/secure/dir", "cryptfile_pass.cfg"
            )

    def test_native_file_path_wins_over_dir(
        self, mock_get_user, mock_get_password, mock_get_keyring
    ):
        backend = mock_get_keyring.return_value
        backend.filename = "cryptfile_pass.cfg"
        env = os.environ.copy()
        env["KEYRING_PROPERTY_FILE_PATH"] = "/native/path/keyring.cfg"
        env["CLOUDSMITH_KEYRING_DIR"] = "/secure/dir"
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert backend.file_path == "/native/path/keyring.cfg"

    def test_alias_file_path_wins_over_dir(
        self, mock_get_user, mock_get_password, mock_get_keyring
    ):
        backend = mock_get_keyring.return_value
        backend.filename = "cryptfile_pass.cfg"
        env = os.environ.copy()
        env.pop("KEYRING_PROPERTY_FILE_PATH", None)
        env["CLOUDSMITH_KEYRING_FILE_PATH"] = "/alias/path/keyring.cfg"
        env["CLOUDSMITH_KEYRING_DIR"] = "/secure/dir"
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert backend.file_path == "/alias/path/keyring.cfg"

    def test_no_op_for_backends_without_filename(
        self, mock_get_user, mock_get_password, mock_get_keyring
    ):
        backend = mock_get_keyring.return_value
        del backend.filename
        backend.file_path = "untouched"
        env = os.environ.copy()
        env.pop("KEYRING_PROPERTY_FILE_PATH", None)
        env["CLOUDSMITH_KEYRING_DIR"] = "/secure/dir"
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert backend.file_path == "untouched"

    def test_no_op_when_dir_not_set(
        self, mock_get_user, mock_get_password, mock_get_keyring
    ):
        backend = mock_get_keyring.return_value
        backend.filename = "cryptfile_pass.cfg"
        backend.file_path = "untouched"
        env = os.environ.copy()
        env.pop("KEYRING_PROPERTY_FILE_PATH", None)
        env.pop("CLOUDSMITH_KEYRING_DIR", None)
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert backend.file_path == "untouched"

    def test_expands_user_and_env_vars(
        self, mock_get_user, mock_get_password, mock_get_keyring
    ):
        backend = mock_get_keyring.return_value
        backend.filename = "keyring_pass.cfg"
        env = os.environ.copy()
        env.pop("KEYRING_PROPERTY_FILE_PATH", None)
        env["KEYRING_STORE_ROOT"] = "/secure"
        env["CLOUDSMITH_KEYRING_DIR"] = "$KEYRING_STORE_ROOT/store"
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert backend.file_path == os.path.join(
                "/secure/store", "keyring_pass.cfg"
            )

    def test_expands_home_directory(
        self, mock_get_user, mock_get_password, mock_get_keyring
    ):
        backend = mock_get_keyring.return_value
        backend.filename = "keyring_pass.cfg"
        env = os.environ.copy()
        env.pop("KEYRING_PROPERTY_FILE_PATH", None)
        env["CLOUDSMITH_KEYRING_DIR"] = "~/store"
        with patch.dict(os.environ, env, clear=True):
            get_access_token(self.api_host)
            assert backend.file_path == os.path.join(
                os.path.expanduser("~/store"), "keyring_pass.cfg"
            )


class TestKeyringFileRelocation:
    """Tests for file relocation with a real cryptfile backend."""

    api_host = "https://example.com"

    @staticmethod
    def _relocation_env(tmp_path):
        env = os.environ.copy()
        for var in (
            "KEYRING_PROPERTY_FILE_PATH",
            "KEYRING_PROPERTY_KEYRING_KEY",
            "CLOUDSMITH_KEYRING_FILE_PATH",
            "CLOUDSMITH_KEYRING_DIR",
            "CLOUDSMITH_KEYRING_KEY",
        ):
            env.pop(var, None)
        env["XDG_DATA_HOME"] = str(tmp_path / "default")
        env["CLOUDSMITH_KEYRING_KEY"] = "test-password"
        return env

    def _roundtrip_token(self, backend, env):
        import keyring

        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(keyring, "set_password", side_effect=backend.set_password),
            patch.object(keyring, "get_password", side_effect=backend.get_password),
        ):
            store_access_token(self.api_host, "token-value")
            assert get_access_token(self.api_host) == "token-value"

    def test_dir_relocates_storage_before_unlock(
        self, tmp_path, mock_get_user, mock_get_keyring
    ):
        backend = CryptFileKeyring()
        mock_get_keyring.return_value = backend
        env = self._relocation_env(tmp_path)
        env["CLOUDSMITH_KEYRING_DIR"] = str(tmp_path / "secure")

        self._roundtrip_token(backend, env)

        assert (tmp_path / "secure" / backend.filename).is_file()
        assert not (tmp_path / "default").exists()

    def test_file_path_alias_relocates_storage_before_unlock(
        self, tmp_path, mock_get_user, mock_get_keyring
    ):
        backend = CryptFileKeyring()
        mock_get_keyring.return_value = backend
        target = tmp_path / "secure" / "tokens.cfg"
        env = self._relocation_env(tmp_path)
        env["CLOUDSMITH_KEYRING_FILE_PATH"] = str(target)

        self._roundtrip_token(backend, env)

        assert target.is_file()
        assert not (tmp_path / "default").exists()


class TestDeleteSsoTokens:
    """Tests for the delete_sso_tokens and has_sso_tokens functions."""

    from keyring.errors import KeyringError

    api_host = "https://example.com"

    def test_delete_sso_tokens(self, mock_get_user, mock_delete_password):
        assert delete_sso_tokens(self.api_host) is True
        assert mock_delete_password.call_count == 3

    def test_delete_sso_tokens_handles_keyring_error(
        self, mock_get_user, mock_delete_password
    ):
        from keyring.errors import KeyringError

        mock_delete_password.side_effect = KeyringError("err")
        assert delete_sso_tokens(self.api_host) is False

    @pytest.mark.parametrize(
        "return_value, expected",
        [
            ("some_token", True),
            (None, False),
            (KeyringError("err"), False),
        ],
    )
    def test_has_sso_tokens(
        self, mock_get_user, mock_get_password, return_value, expected
    ):
        if isinstance(return_value, Exception):
            mock_get_password.side_effect = return_value
        else:
            mock_get_password.return_value = return_value
        assert has_sso_tokens(self.api_host) is expected

    def test_has_sso_tokens_returns_false_when_keyring_disabled(
        self, mock_get_user, mock_get_password
    ):
        """has_sso_tokens should short-circuit when keyring is disabled."""
        mock_get_password.return_value = "some_token"
        with patch.dict(os.environ, {"CLOUDSMITH_NO_KEYRING": "1"}):
            assert has_sso_tokens(self.api_host) is False
        mock_get_password.assert_not_called()
