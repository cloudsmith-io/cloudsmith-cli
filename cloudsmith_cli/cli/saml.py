from urllib.parse import urlencode

import requests

from ..core.api.exceptions import ApiException
from ..core.sso import (
    MISSING_SAML_TOKENS,
    raise_for_api_error,
    refresh_access_token,
    response_json_object,
)

__all__ = [
    "exchange_2fa_token",
    "get_idp_url",
    "raise_for_api_error",
    "refresh_access_token",
]


MISSING_IDP_URL = "The API did not return a SAML IdP URL."


def get_idp_url(
    api_host: str, owner: str, session: requests.Session, redirect_url: str
) -> str:
    org_saml_url = "{api_host}/orgs/{owner}/saml/?{params}".format(
        api_host=api_host,
        owner=owner,
        params=urlencode({"redirect_url": redirect_url}),
    )

    org_saml_response = session.get(org_saml_url, timeout=30)

    raise_for_api_error(org_saml_response)

    idp_url = response_json_object(org_saml_response, MISSING_IDP_URL).get(
        "redirect_url"
    )
    if not isinstance(idp_url, str) or not idp_url:
        raise ApiException(0, detail=MISSING_IDP_URL)
    return idp_url


def exchange_2fa_token(
    api_host: str, two_factor_token: str, totp_token: str, session: requests.Session
) -> tuple[str, str | None]:
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

    exchange_data = response_json_object(exchange_response, MISSING_SAML_TOKENS)
    access_token = exchange_data.get("access_token")
    refresh_token = exchange_data.get("refresh_token")
    if not access_token:
        raise ApiException(0, detail=MISSING_SAML_TOKENS)

    return (access_token, refresh_token)
