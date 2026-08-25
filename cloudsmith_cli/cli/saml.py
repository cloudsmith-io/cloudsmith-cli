from urllib.parse import urlencode

import requests

from ..core.api.exceptions import ApiException


def create_configured_session(opts):
    """
    Create a requests session configured with the options from opts.
    """
    session = requests.Session()

    if hasattr(opts, "api_ssl_verify") and opts.api_ssl_verify is not None:
        session.verify = opts.api_ssl_verify

    if hasattr(opts, "api_proxy") and opts.api_proxy:
        session.proxies = {"http": opts.api_proxy, "https": opts.api_proxy}

    if hasattr(opts, "api_user_agent") and opts.api_user_agent:
        session.headers.update({"User-Agent": opts.api_user_agent})

    if hasattr(opts, "api_headers") and opts.api_headers:
        session.headers.update(opts.api_headers)

    return session


def raise_for_api_error(response):
    """Raise :class:`ApiException` if *response* failed, keeping the API's detail.

    Without the detail the exception renders as bare status text, so a caller
    reporting it tells the user that something failed but never what.
    """
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        try:
            body = exc.response.json()
        except ValueError:
            body = None

        raise ApiException(
            response.status_code,
            detail=body.get("detail") if isinstance(body, dict) else None,
            headers=exc.response.headers,
            body=exc.response.content,
        )


def get_idp_url(api_host, owner, session):
    org_saml_url = "{api_host}/orgs/{owner}/saml/?{params}".format(
        api_host=api_host,
        owner=owner,
        params=urlencode({"redirect_url": "http://localhost:12400"}),
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


def refresh_access_token(api_host, access_token, refresh_token, session):
    data = {"refresh_token": refresh_token}
    url = f"{api_host}/user/refresh-token/"

    headers = {"Authorization": f"Bearer {access_token}"}

    response = session.post(
        url,
        data=data,
        headers=headers,
        timeout=30,
    )

    raise_for_api_error(response)

    response_data = response.json()
    access_token = response_data.get("access_token")
    refresh_token = response_data.get("refresh_token")

    return (access_token, refresh_token)
