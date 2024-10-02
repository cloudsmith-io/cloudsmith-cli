import getpass
from datetime import datetime

import keyring

ACCESS_TOKEN_KEY = "cloudsmith_cli-access_token-{api_host}"
ACCESS_TOKEN_REFRESHED_AT_KEY = "cloudsmith_cli-access_token_refreshed_at-{api_host}"
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


def store_access_token_refreshed_at(api_host, refresh_time=None):
    if refresh_time is None:
        refresh_time = datetime.utcnow()

    refreshed_at_value = refresh_time.isoformat()

    username = _get_username()
    key = ACCESS_TOKEN_REFRESHED_AT_KEY.format(api_host=api_host)
    keyring.set_password(key, username, refreshed_at_value)


def get_access_token_refreshed_at(api_host):
    username = _get_username()
    key = ACCESS_TOKEN_REFRESHED_AT_KEY.format(api_host=api_host)
    return keyring.get_password(key, username)


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
        store_access_token_refreshed_at(api_host=api_host)

    if refresh_token:
        store_refresh_token(api_host=api_host, refresh_token=refresh_token)
