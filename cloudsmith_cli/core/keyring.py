import getpass
from datetime import datetime, timedelta

import keyring

ACCESS_TOKEN_KEY = "cloudsmith_cli-access_token-{api_host}"
ACCESS_TOKEN_REFRESH_ATTEMPTED_AT_KEY = (
    "cloudsmith_cli-access_token_refresh_attempted_at-{api_host}"
)
REFRESH_TOKEN_KEY = "cloudsmith_cli-refresh_token-{api_host}"


def _get_username():
    return getpass.getuser()


def store_access_token(api_host, access_token):
    username = _get_username()
    key = ACCESS_TOKEN_KEY.format(api_host=api_host)
    keyring.set_password(key, username, access_token)


def get_access_token(api_host):
    username = _get_username()
    key = ACCESS_TOKEN_KEY.format(api_host=api_host)
    return keyring.get_password(key, username)


def update_refresh_attempted_at(api_host, refresh_time=None):
    if refresh_time is None:
        refresh_time = datetime.utcnow()

    refresh_attempted_at_value = refresh_time.isoformat()

    username = _get_username()
    key = ACCESS_TOKEN_REFRESH_ATTEMPTED_AT_KEY.format(api_host=api_host)
    keyring.set_password(key, username, refresh_attempted_at_value)


def get_refresh_attempted_at(api_host):
    username = _get_username()
    key = ACCESS_TOKEN_REFRESH_ATTEMPTED_AT_KEY.format(api_host=api_host)
    value = keyring.get_password(key, username)

    if value:
        return datetime.fromisoformat(value)

    return None


def should_refresh_access_token(api_host):
    token_refreshed_at = get_refresh_attempted_at(api_host)

    if token_refreshed_at:
        return token_refreshed_at < (datetime.utcnow() - timedelta(minutes=30))

    return True


def store_refresh_token(api_host, refresh_token):
    username = _get_username()
    key = REFRESH_TOKEN_KEY.format(api_host=api_host)
    keyring.set_password(key, username, refresh_token)


def get_refresh_token(api_host):
    username = _get_username()
    key = REFRESH_TOKEN_KEY.format(api_host=api_host)
    return keyring.get_password(key, username)


def store_sso_tokens(api_host, access_token, refresh_token):
    if access_token:
        store_access_token(api_host=api_host, access_token=access_token)
        update_refresh_attempted_at(api_host=api_host)

    if refresh_token:
        store_refresh_token(api_host=api_host, refresh_token=refresh_token)
