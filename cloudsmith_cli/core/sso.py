"""SSO token refresh against the Cloudsmith API."""

import requests

from .api.exceptions import ApiException


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
