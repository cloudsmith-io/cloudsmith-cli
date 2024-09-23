import getpass

import keyring


def get_username():
    return getpass.getuser()


def store_access_token(access_token):
    username = get_username()
    keyring.set_password("cloudsmith_cli-access_token", username, access_token)


def get_access_token():
    username = get_username()
    return keyring.get_password("cloudsmith_cli-access_token", username)


def store_refresh_token(refresh_token):
    username = get_username()
    keyring.set_password("cloudsmith_cli-refresh_token", username, refresh_token)


def get_refresh_token():
    username = get_username()
    return keyring.get_password("cloudsmith_cli-refresh_token", username)


def store_sso_tokens(access_token, refresh_token):
    if access_token:
        store_access_token(access_token)

    if refresh_token:
        store_refresh_token(refresh_token)
