import getpass
import os
from datetime import datetime, timedelta

import keyring
from keyring.errors import KeyringError

ACCESS_TOKEN_KEY = "cloudsmith_cli-access_token-{api_host}"


def should_use_keyring():
    """Check if keyring should be used based on CLOUDSMITH_NO_KEYRING env var."""
    env_value = os.environ.get("CLOUDSMITH_NO_KEYRING", "").strip().lower()
    return env_value not in ("1", "true", "yes")


ACCESS_TOKEN_REFRESH_ATTEMPTED_AT_KEY = (
    "cloudsmith_cli-access_token_refresh_attempted_at-{api_host}"
)
REFRESH_TOKEN_KEY = "cloudsmith_cli-refresh_token-{api_host}"


def _get_username():
    return getpass.getuser()


def _get_value(key):
    username = _get_username()
    try:
        return keyring.get_password(key, username)
    except KeyringError:
        return None


def _set_value(key, value):
    username = _get_username()
    keyring.set_password(key, username, value)


def store_access_token(api_host, access_token):
    key = ACCESS_TOKEN_KEY.format(api_host=api_host)
    _set_value(key, access_token)


def get_access_token(api_host):
    if not should_use_keyring():
        return None
    key = ACCESS_TOKEN_KEY.format(api_host=api_host)
    return _get_value(key)


def update_refresh_attempted_at(api_host, refresh_time=None):
    if refresh_time is None:
        refresh_time = datetime.utcnow()

    refresh_attempted_at_value = refresh_time.isoformat()

    key = ACCESS_TOKEN_REFRESH_ATTEMPTED_AT_KEY.format(api_host=api_host)
    _set_value(key, refresh_attempted_at_value)


def get_refresh_attempted_at(api_host):
    key = ACCESS_TOKEN_REFRESH_ATTEMPTED_AT_KEY.format(api_host=api_host)
    value = _get_value(key)

    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def should_refresh_access_token(api_host):
    if not should_use_keyring():
        return False

    token_refreshed_at = get_refresh_attempted_at(api_host)

    if token_refreshed_at:
        return token_refreshed_at < (datetime.utcnow() - timedelta(minutes=30))

    return True


def store_refresh_token(api_host, refresh_token):
    key = REFRESH_TOKEN_KEY.format(api_host=api_host)
    _set_value(key, refresh_token)


def get_refresh_token(api_host):
    key = REFRESH_TOKEN_KEY.format(api_host=api_host)
    return _get_value(key)


def store_sso_tokens(api_host, access_token, refresh_token):
    """Store SSO tokens in keyring if enabled."""
    if not should_use_keyring():
        return False

    if access_token:
        store_access_token(api_host=api_host, access_token=access_token)
        update_refresh_attempted_at(api_host=api_host)

    if refresh_token:
        store_refresh_token(api_host=api_host, refresh_token=refresh_token)

    return True


def _delete_value(key):
    username = _get_username()
    try:
        keyring.delete_password(key, username)
        return True
    except KeyringError:
        return False


def _sso_keys(api_host):
    """Return the keyring service names for all SSO-related entries."""
    return [
        ACCESS_TOKEN_KEY.format(api_host=api_host),
        REFRESH_TOKEN_KEY.format(api_host=api_host),
        ACCESS_TOKEN_REFRESH_ATTEMPTED_AT_KEY.format(api_host=api_host),
    ]


def has_sso_tokens(api_host):
    """Check if any SSO tokens exist in the keyring for the given host."""
    return any(_get_value(key) for key in _sso_keys(api_host))


def delete_sso_tokens(api_host):
    """Delete all SSO tokens from the keyring for the given host."""
    results = [_delete_value(key) for key in _sso_keys(api_host)]
    return any(results)
