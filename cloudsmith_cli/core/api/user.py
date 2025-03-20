"""API - User endpoints."""

import cloudsmith_api
import json
import click
from cloudsmith_api.rest import ApiException

from .. import ratelimits
from .exceptions import catch_raise_api_exception
from .init import get_api_client, unset_api_key


def get_user_api():
    """Get the user API client."""
    return get_api_client(cloudsmith_api.UserApi)


def get_user_token(login, password, totp_token=None, two_factor_token=None):
    """Retrieve user token from the API (via authentication)."""
    client = get_user_api()

    # Never use API key for the token endpoint
    unset_api_key()

    # Prepare data based on whether this is initial login or 2FA completion
    if totp_token and two_factor_token:
        data_dict = {
            "totp_token": totp_token,
            "two_factor_token": two_factor_token,
        }
    else:
        data_dict = {
            "email": login,
            "password": password,
        }

    try:
        data, response, headers = client.user_token_create_with_http_info(data=data_dict)
        ratelimits.maybe_rate_limit(client, headers)
        return data.token
    except ApiException as e:
        # Check if this is a 2FA required response TODO: Is this right way to go? Feels wrong
        if e.status == 422:
            try:
                response_data = json.loads(e.body)
                if response_data.get("two_factor_required"):
                    # Clear the current line 
                    click.echo("\r\003[k", nl=False)

                    # Notify that 2FA required
                    click.echo("Two-factor authentication is required.")
                    two_factor_token = response_data.get("two_factor_token")

                    # Prompt user for their 2FA code
                    totp_token = click.prompt("Enter your two-factor authentication code", type=str)

                    click.echo(
                        "Verifying two-factor code for %(login)s ... " 
                        % {"login": click.style(login, bold=True)},
                        nl=False
                    )

                    return get_user_token(
                        login=login,
                        password=password,
                        totp_token=totp_token,
                        two_factor_token=two_factor_token,
                    )
            except (ValueError, KeyError):
                # If we can't parse the response body as JSON or it doesn't have the expected structure
                pass
        raise


def get_user_brief():
    """Retrieve brief for current user (if any)."""
    client = get_user_api()

    with catch_raise_api_exception():
        data, _, headers = client.user_self_with_http_info()

    ratelimits.maybe_rate_limit(client, headers)
    return data.authenticated, data.slug, data.email, data.name
