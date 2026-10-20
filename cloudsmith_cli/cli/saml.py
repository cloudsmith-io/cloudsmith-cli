from urllib.parse import urlencode

from ..core.sso import raise_for_api_error, refresh_access_token

__all__ = [
    "exchange_2fa_token",
    "get_idp_url",
    "raise_for_api_error",
    "refresh_access_token",
]


def get_idp_url(api_host, owner, session, redirect_url):
    org_saml_url = "{api_host}/orgs/{owner}/saml/?{params}".format(
        api_host=api_host,
        owner=owner,
        params=urlencode({"redirect_url": redirect_url}),
    )

    org_saml_response = session.get(org_saml_url, timeout=30)

    raise_for_api_error(org_saml_response)

    return org_saml_response.json().get("redirect_url")


def exchange_2fa_token(api_host, two_factor_token, totp_token, session):
    exchange_data = {"two_factor_token": two_factor_token, "totp_token": totp_token}
    exchange_url = f"{api_host}/user/two-factor/"

    headers = {"Authorization": f"Bearer {two_factor_token}"}

    exchange_response = session.post(
        exchange_url,
        data=exchange_data,
        headers=headers,
        timeout=30,
    )

    raise_for_api_error(exchange_response)

    exchange_data = exchange_response.json()
    access_token = exchange_data.get("access_token")
    refresh_token = exchange_data.get("refresh_token")

    return (access_token, refresh_token)
